#!/usr/bin/env python3
"""The music engine helper: ACE-Step on this Mac, looked after for the AI Hub.

ACE-Step (https://github.com/ace-step/ACE-Step-1.5, MIT) makes songs from a description and
lyrics, and remakes recordings. It needs the Mac's own graphics chip, so it can't run in Docker
with the apps: it lives on the Mac, under ``~/.local/share/music_engine``, and this small server
looks after it the way Ollama is looked after for the text models. It runs as a LaunchAgent
(installed by ``macos_music_engine.sh``), listens on 127.0.0.1 only, and the AI Hub reaches it as
``http://host.docker.internal:<port>``, which Docker Desktop forwards to the Mac's loopback.

What it does for the hub:

- says what is here (``GET /status``): whether ACE-Step and its weights are installed, which
  size was chosen for this Mac, how much disk and memory there is, whether the engine's server
  is stopped, starting, ready or busy;
- installs the engine on request (``POST /install``), with progress in the status;
- starts the engine's server when a job comes and stops it after a while idle, so its memory
  goes back to the Mac in between;
- takes generation jobs (``POST /generate`` → ``{"id"}``; ``GET /job/<id>``; ``GET
  /job/<id>/audio``), queueing them to ACE-Step's own API server (``release_task``,
  ``query_result``, ``/v1/audio``) and keeping each song's file.

Every request but ``GET /ping`` carries a token signed with the platform's ``DDNS_AUTH_SECRET``
(audience ``music-engine``), the way the apps sign their asks to the hub; the installer stores
the secret in ``~/.re_ddns/music-engine.json`` (0600). Standard library only (the Mac's own
python3 runs it).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

VERSION = "1"
DEFAULT_PORT = 3144
AUDIENCE = "music-engine"
HOME = Path.home()
APP_DIR = HOME / ".re_ddns"
# The config holds the port, the size and the platform secret; tests point MUSIC_ENGINE_CONFIG at one of their own.
CONFIG = Path(os.environ.get("MUSIC_ENGINE_CONFIG") or APP_DIR / "music-engine.json")
LOG_FILE = APP_DIR / "music-engine.log"
ENGINE_DIR = HOME / ".local" / "share" / "music_engine"
REPO = ENGINE_DIR / "ACE-Step-1.5"
CHECKPOINTS = REPO / "checkpoints"
SONGS = ENGINE_DIR / "songs"
# A recording to remake: ACE-Step reads source audio only from the system's temp folder.
UPLOADS = Path(tempfile.gettempdir()) / "music_engine_uploads"
ACESTEP_PORT = 8001
ACESTEP_COMMIT = "ca1e85fe94"  # pinned: what this helper was tested with
IDLE_MINUTES = 20
START_TIMEOUT = 900  # seconds the engine may take to load its models
JOB_TIMEOUT = 1800
KEEP_SONGS = 40

# What each size installs: the parts of ACE-Step/Ace-Step1.5 and the language model that plans
# the song's structure. "standard" is the whole unified repo; "small" swaps its 1.7B planner for
# the 0.6B one and fits a 16 GB Mac. Sizes are the weights on disk (GB).
TIERS = {
    "small": {"lm": "acestep-5Hz-lm-0.6B", "gb": 7.7, "memory_gb": 16, "words": "the song model and the small planner (0.6B)"},
    "standard": {"lm": "acestep-5Hz-lm-1.7B", "gb": 10.1, "memory_gb": 24, "words": "the song model and the normal planner (1.7B)"},
}
PARTS = {
    "small": ["acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B", "acestep-5Hz-lm-0.6B"],
    "standard": ["acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B", "acestep-5Hz-lm-1.7B"],
}
ENV_GB = 5.0  # the Python environment, about
MARGIN_GB = 6.0  # left free after the install


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)


# ------------------------------------------------------------ the Mac


def memory_gb() -> float:
    # The full path: a LaunchAgent's PATH has no /usr/sbin.
    try:
        return int(subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout) / 1024**3
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def disk_free_gb(path: Path = ENGINE_DIR) -> float:
    where = path
    while not where.exists() and where != where.parent:
        where = where.parent
    return shutil.disk_usage(where).free / 1024**3


def choose_tier(ram: float = 0.0) -> str:
    """The size that fits this Mac: the normal planner from 24 GB of memory, the small one below.
    When the memory can't be read, the normal one: a Mac that can't hold it says so at start."""
    ram = ram or memory_gb()
    return "small" if 0 < ram < 24 else "standard"


def fits(tier: str) -> tuple[bool, str]:
    """Whether ``tier`` has the room it needs here, and why not."""
    need = TIERS[tier]["gb"] + (0 if (REPO / ".venv").exists() else ENV_GB) + MARGIN_GB - installed_gb(tier)
    free = disk_free_gb()
    if free < need:
        return False, f"needs {need:.0f} GB free on the disk, there are {free:.0f} GB"
    ram = memory_gb()
    if ram and ram < 16:
        return False, f"needs a Mac with 16 GB of memory or more, this one has {ram:.0f} GB"
    return True, ""


def dir_gb(path: Path) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e9


def installed_gb(tier: str) -> float:
    return sum(dir_gb(CHECKPOINTS / part) for part in PARTS[tier] if (CHECKPOINTS / part).is_dir())


def part_whole(root: Path, part: str) -> bool:
    """Whether a part is here whole: its config, a weights file of some size, and nothing of it
    still downloading (huggingface_hub keeps the unfinished files under ``.cache``)."""
    folder = root / part
    if not folder.is_dir() or not any(folder.glob("*.json")):
        return False
    if not any(f.is_file() and f.stat().st_size > 100_000_000 for f in folder.rglob("*")):
        return False
    pending = root / ".cache" / "huggingface" / "download" / part
    return not (pending.is_dir() and any(pending.rglob("*.incomplete")))


def weights_missing(tier: str) -> list[str]:
    """The parts of ``tier`` not here whole."""
    return [part for part in PARTS[tier] if not part_whole(CHECKPOINTS, part)]


def engine_installed() -> bool:
    return (REPO / ".venv" / "bin" / "acestep-api").exists() and (REPO / "acestep").is_dir()


# ------------------------------------------------------------ tokens


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify(authorization: str, secret: str) -> dict:
    """The claims of a bearer token signed with ``secret`` (HS256), or a ValueError."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or token.count(".") != 2:
        raise ValueError("needs Authorization: Bearer <token>")
    head, body, sig = token.split(".")
    want = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(want), sig):
        raise ValueError("wrong signature")
    try:
        claims = json.loads(_unb64(body))
    except ValueError as e:
        raise ValueError("unreadable token") from e
    if claims.get("aud") != AUDIENCE:
        raise ValueError("this token is for something else")
    if float(claims.get("exp") or 0) < time.time():
        raise ValueError("expired token")
    return claims


# ------------------------------------------------------------ the engine's server


class Engine:
    """ACE-Step's API server as a child process: started when needed, stopped when idle."""

    def __init__(self, tier: str):
        self.tier = tier
        self.proc: subprocess.Popen | None = None
        self.state = "stopped"  # stopped, starting, ready, failed
        self.error = ""
        self.lock = threading.Lock()
        self.last_used = time.time()
        self.started_at = 0.0

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{ACESTEP_PORT}{path}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url("/health"), timeout=5) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def start(self) -> None:
        with self.lock:
            if self.alive():
                return
            if not engine_installed() or weights_missing(self.tier):
                self.state, self.error = "failed", "the engine isn't installed"
                return
            SONGS.mkdir(parents=True, exist_ok=True)
            env = {
                **os.environ,
                "ACESTEP_LM_BACKEND": "mlx",
                "TOKENIZERS_PARALLELISM": "false",
                "ACESTEP_INIT_LLM": "true",
                "ACESTEP_LM_MODEL_PATH": TIERS[self.tier]["lm"],
                "ACESTEP_CONFIG_PATH": "acestep-v15-turbo",
                "ACESTEP_NO_INIT": "false",
                "ACESTEP_DOWNLOAD_SOURCE": "huggingface",
                "ACESTEP_API_HOST": "127.0.0.1",
                "ACESTEP_API_PORT": str(ACESTEP_PORT),
                "HF_HUB_OFFLINE": "1",
                "PYTHONUNBUFFERED": "1",
            }
            log_file = open(ENGINE_DIR / "acestep.log", "ab")  # noqa: SIM115 - the child owns it
            self.proc = subprocess.Popen(
                [str(REPO / ".venv" / "bin" / "acestep-api"), "--host", "127.0.0.1", "--port", str(ACESTEP_PORT)],
                cwd=str(REPO),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.state, self.error, self.started_at = "starting", "", time.time()
            log(f"engine starting (pid {self.proc.pid}, {self.tier})")
            threading.Thread(target=self._watch_start, daemon=True).start()

    def _watch_start(self) -> None:
        while self.alive() and time.time() - self.started_at < START_TIMEOUT:
            if self.ping():
                self.state = "ready"
                log(f"engine ready after {time.time() - self.started_at:.0f} s")
                return
            time.sleep(2)
        self.state, self.error = "failed", "the engine's server stopped while starting; see acestep.log" if not self.alive() else "the engine took too long to start"
        log(f"engine failed to start: {self.error}")
        self.stop()

    def ready(self, wait: float = START_TIMEOUT) -> bool:
        """Starts the server if it isn't up, and waits for it."""
        if self.state == "ready" and self.alive():
            return True
        self.start()
        end = time.time() + wait
        while time.time() < end:
            if self.state == "ready":
                return True
            if self.state == "failed":
                return False
            time.sleep(1)
        return False

    def stop(self) -> None:
        with self.lock:
            proc, self.proc = self.proc, None
            self.state = "stopped"
        if proc is None or proc.poll() is not None:
            return
        log("engine stopping")
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=30)
        except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def call(self, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url(path), data=data, headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def fetch(self, path: str, dest: Path) -> None:
        with urllib.request.urlopen(self.url(path), timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)


# ------------------------------------------------------------ jobs


class Jobs:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.queue = threading.Semaphore(1)  # one song at a time: the Mac's memory is shared

    def add(self, spec: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "state": "waiting", "at": time.time(), "secs": 0.0, "error": "", "metas": {}, "file": "", "spec": spec}
        with self.lock:
            self.jobs[job_id] = job
            for old in sorted(self.jobs.values(), key=lambda j: j["at"])[:-KEEP_SONGS]:
                self.jobs.pop(old["id"], None)
                if old.get("file"):
                    Path(old["file"]).unlink(missing_ok=True)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job_id

    def get(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return {k: v for k, v in job.items() if k != "spec"} | {"secs": round(time.time() - job["at"] if job["state"] in ("waiting", "starting", "running") else job["secs"], 1)}

    def busy(self) -> int:
        return sum(1 for j in self.jobs.values() if j["state"] in ("waiting", "starting", "running"))

    def _run(self, job: dict) -> None:
        engine = self.engine
        with self.queue:
            engine.last_used = time.time()
            job["state"] = "starting"
            if not engine.ready():
                job["state"], job["error"] = "failed", engine.error or "the engine didn't start"
                return
            job["state"] = "running"
            try:
                self._generate(job)
            except Exception as e:  # noqa: BLE001 - told to the hub
                job["state"], job["error"] = "failed", f"{type(e).__name__}: {e}"
                log(f"job {job['id']} failed: {job['error']}")
            finally:
                job["secs"] = round(time.time() - job["at"], 1)
                engine.last_used = time.time()

    def _generate(self, job: dict) -> None:
        engine = self.engine
        spec = job["spec"]
        body = {
            "prompt": spec.get("caption") or "",
            "lyrics": spec.get("lyrics") or "[Instrumental]",
            "task_type": spec.get("task") or "text2music",
            "vocal_language": spec.get("language") or "en",
            "audio_format": "mp3",
            "batch_size": 1,
            "thinking": bool(spec.get("thinking", True)),
            "use_random_seed": not spec.get("seed"),
            "seed": int(spec.get("seed") or -1),
            "inference_steps": int(spec.get("steps") or 8),
        }
        for key in ("bpm", "key_scale", "time_signature"):
            if spec.get(key):
                body[key] = spec[key]
        if spec.get("duration"):
            body["audio_duration"] = max(10, min(600, int(spec["duration"])))
        if spec.get("audio_b64"):
            UPLOADS.mkdir(parents=True, exist_ok=True)
            src = UPLOADS / f"{job['id']}.{spec.get('audio_format') or 'mp3'}"
            src.write_bytes(base64.b64decode(spec["audio_b64"]))
            body["src_audio_path"] = str(src)
            if "cover_strength" in spec:
                body["audio_cover_strength"] = float(spec["cover_strength"])
            if spec.get("repaint_start") is not None:
                body["repainting_start"] = float(spec["repaint_start"])
                body["repainting_end"] = float(spec.get("repaint_end") or -1)
        released = engine.call("/release_task", body, timeout=120)
        task = (released.get("data") or {}).get("task_id") or released.get("task_id")
        if not task:
            raise RuntimeError(f"ACE-Step took no task: {str(released)[:200]}")
        job["task"] = task
        end = time.time() + JOB_TIMEOUT
        while time.time() < end:
            time.sleep(2)
            answer = engine.call("/query_result", {"task_id_list": [task]}, timeout=60)
            rows = answer.get("data") or []
            row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
            status = row.get("status")
            if status in (1, "1", "succeeded"):
                result = row.get("result")
                if isinstance(result, str):
                    result = json.loads(result)
                if isinstance(result, list):
                    result = result[0] if result else {}
                file_path = result.get("file") or ""
                if not file_path:
                    raise RuntimeError("ACE-Step finished without a file")
                dest = SONGS / f"{job['id']}.mp3"
                engine.fetch(file_path if file_path.startswith("/v1/") else f"/v1/audio?path={urllib.request.quote(file_path, safe='')}", dest)
                job["file"] = str(dest)
                job["metas"] = {k: result.get("metas", {}).get(k) for k in ("bpm", "duration", "keyscale", "genres")} if isinstance(result.get("metas"), dict) else {}
                job["models"] = {"dit": result.get("dit_model"), "lm": result.get("lm_model")}
                job["state"] = "done"
                log(f"job {job['id']} done in {time.time() - job['at']:.0f} s")
                return
            if status in (2, "2", "failed"):
                raise RuntimeError(str(row.get("error") or row.get("result") or "ACE-Step failed")[:300])
        raise RuntimeError("the song took too long")


# ------------------------------------------------------------ installing


class Installer:
    """Puts the engine here, in the background: the code (git, pinned), its environment (uv) and
    the weights of one size (huggingface_hub, run with the engine's own Python)."""

    def __init__(self):
        self.state = "idle"  # idle, running, done, failed
        self.step = ""
        self.error = ""
        self.tier = ""
        self.thread: threading.Thread | None = None

    def status(self) -> dict:
        out = {"state": self.state, "step": self.step, "error": self.error, "tier": self.tier}
        if self.state == "running" and self.tier and self.step == "weights":
            out["gb_done"] = round(installed_gb(self.tier), 2)
            out["gb_total"] = TIERS[self.tier]["gb"]
        return out

    def start(self, tier: str) -> str:
        if self.state == "running":
            return "already installing"
        ok, why = fits(tier)
        if not ok:
            return why
        self.state, self.step, self.error, self.tier = "running", "code", "", tier
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return ""

    def _sh(self, cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
        log("install: " + " ".join(cmd))
        with open(ENGINE_DIR / "install.log", "ab") as out:
            done = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=out, stderr=subprocess.STDOUT)
        if done.returncode:
            raise RuntimeError(f"{cmd[0]} failed ({done.returncode}); see {ENGINE_DIR / 'install.log'}")

    def _run(self) -> None:
        try:
            ENGINE_DIR.mkdir(parents=True, exist_ok=True)
            uv = shutil.which("uv") or next((p for p in (HOME / ".local/bin/uv", HOME / ".cargo/bin/uv", Path("/opt/homebrew/bin/uv")) if p.exists()), None)
            if uv is None:
                raise RuntimeError("uv isn't installed: brew install uv, or curl -LsSf https://astral.sh/uv/install.sh | sh")
            git = shutil.which("git")
            if git is None:
                raise RuntimeError("git isn't installed: xcode-select --install")
            self.step = "code"
            if not (REPO / ".git").is_dir():
                self._sh([git, "clone", "--quiet", "https://github.com/ace-step/ACE-Step-1.5.git", str(REPO)])
            self._sh([git, "-c", "advice.detachedHead=false", "checkout", "--quiet", ACESTEP_COMMIT], cwd=REPO)
            self.step = "environment"
            if not (REPO / ".venv" / "bin" / "acestep-api").exists():
                # Hundreds of packages (torch, mlx...): a slow link times out once in a while, so twice.
                env = {**os.environ, "UV_PYTHON_PREFERENCE": "managed", "UV_HTTP_TIMEOUT": "600"}
                try:
                    self._sh([str(uv), "sync", "--no-progress", "--python", "3.12"], cwd=REPO, env=env)
                except RuntimeError:
                    self._sh([str(uv), "sync", "--no-progress", "--python", "3.12"], cwd=REPO, env=env)
            self.step = "weights"
            # Plain HTTP downloads: the chunked (xet) way stalled on a slow link.
            self._sh([str(REPO / ".venv" / "bin" / "python"), str(Path(__file__).with_name("download_weights.py")), self.tier, str(CHECKPOINTS)], env={**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1", "HF_HUB_DISABLE_XET": "1"})
            missing = weights_missing(self.tier)
            if missing:
                raise RuntimeError(f"still missing after the download: {', '.join(missing)}")
            self.state, self.step = "done", ""
            save_config(tier=self.tier)
            log(f"install done ({self.tier})")
        except Exception as e:  # noqa: BLE001 - shown on the hub's page
            self.state, self.error = "failed", str(e)
            log(f"install failed: {e}")


# ------------------------------------------------------------ the server


def save_config(**fields) -> dict:
    cfg = load_config()
    cfg.update(fields)
    APP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = CONFIG.with_name(CONFIG.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cfg, indent=2) + "\n")
    os.replace(tmp, CONFIG)
    return cfg


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = f"music-engine/{VERSION}"
    secret = ""
    engine: Engine
    jobs: Jobs
    installer: Installer

    def log_message(self, format, *args):  # noqa: A002 - the log keeps starts, stops and jobs
        pass

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self) -> bool:
        if not self.secret:
            self._reply(503, {"error": "the helper has no platform secret yet (run macos_music_engine.sh --install)"})
            return False
        try:
            verify(self.headers.get("Authorization", ""), self.secret)
        except ValueError as e:
            self._reply(401, {"error": str(e)})
            return False
        return True

    def _status(self) -> dict:
        tier = load_config().get("tier") or choose_tier()
        missing = weights_missing(tier)
        ok, why = fits(tier)
        return {
            "helper": VERSION,
            "engine": "ACE-Step 1.5",
            "commit": ACESTEP_COMMIT,
            "tier": tier,
            "tiers": {name: {"gb": t["gb"], "memory_gb": t["memory_gb"], "words": t["words"]} for name, t in TIERS.items()},
            "installed": engine_installed() and not missing,
            "code": engine_installed(),
            "missing": missing,
            "gb_installed": round(installed_gb(tier), 2),
            "fits": ok,
            "why_not": why,
            "disk_free_gb": round(disk_free_gb(), 1),
            "memory_gb": round(memory_gb(), 1),
            "server": self.engine.state if self.jobs.busy() == 0 or self.engine.state != "ready" else "busy",
            "server_error": self.engine.error,
            "jobs": self.jobs.busy(),
            "idle_minutes": IDLE_MINUTES,
            "last_used": self.engine.last_used,
            "install": self.installer.status(),
            "engine_dir": str(ENGINE_DIR),
        }

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/ping":
            self._reply(200, {"helper": "music-engine", "version": VERSION})
            return
        if not self._allowed():
            return
        if path == "/status":
            self._reply(200, self._status())
        elif path.startswith("/job/") and path.endswith("/audio"):
            job = self.jobs.jobs.get(path.split("/")[2])
            if job is None or job["state"] != "done" or not job.get("file") or not Path(job["file"]).is_file():
                self._reply(404, {"error": "no such song"})
                return
            data = Path(job["file"]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/job/"):
            job = self.jobs.get(path.split("/")[2])
            self._reply(200 if job else 404, job or {"error": "no such job"})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not self._allowed():
            return
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024 * 1024)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
        except ValueError as e:
            self._reply(400, {"error": str(e)})
            return
        if path == "/install":
            tier = body.get("tier") or load_config().get("tier") or choose_tier()
            if tier not in TIERS:
                self._reply(400, {"error": f"no such size: {tier}"})
                return
            why = self.installer.start(tier)
            self._reply(409 if why else 202, {"error": why} if why else {"started": tier})
        elif path == "/start":
            self.engine.start()
            self._reply(200, {"server": self.engine.state, "error": self.engine.error})
        elif path == "/stop":
            self.engine.stop()
            self._reply(200, {"server": self.engine.state})
        elif path == "/generate":
            if not engine_installed() or weights_missing(load_config().get("tier") or choose_tier()):
                self._reply(503, {"error": "the music engine isn't installed on this Mac yet"})
                return
            self._reply(202, {"id": self.jobs.add(body)})
        else:
            self._reply(404, {"error": "not found"})


def idle_watch(engine: Engine, jobs: Jobs) -> None:
    while True:
        time.sleep(60)
        if engine.alive() and jobs.busy() == 0 and time.time() - engine.last_used > IDLE_MINUTES * 60:
            log(f"idle for {IDLE_MINUTES} min")
            engine.stop()


def main() -> None:
    cfg = load_config()
    port = int(cfg.get("port") or DEFAULT_PORT)
    Handler.secret = str(cfg.get("secret") or "")
    tier = cfg.get("tier") or choose_tier()
    Handler.engine = Engine(tier)
    Handler.jobs = Jobs(Handler.engine)
    Handler.installer = Installer()
    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=idle_watch, args=(Handler.engine, Handler.jobs), daemon=True).start()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True

    def bye(*_):
        Handler.engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, bye)
    log(f"listening on 127.0.0.1:{port} ({tier}; engine {'installed' if engine_installed() and not weights_missing(tier) else 'not installed'})")
    server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        tier = choose_tier()
        print(json.dumps({"tier": tier, "memory_gb": round(memory_gb(), 1), "disk_free_gb": round(disk_free_gb(), 1), "fits": fits(tier)[0], "why_not": fits(tier)[1], "missing": weights_missing(tier), "code": engine_installed()}))
        sys.exit(0)
    main()
