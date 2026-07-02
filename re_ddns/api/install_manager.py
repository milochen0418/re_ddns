"""App Store install orchestration + progress manager (hosted by re-ddns).

The App Store UI (``aapps.reflex-ddns.com``) no longer asks the user to run
``smart_launch.sh`` by hand.  Instead it calls the endpoints in this module,
which drive the **whole install through the Docker Engine API** (over the
bind-mounted ``/var/run/docker.sock``) and expose live progress so the UI can
render a real progress bar.

How an install works
--------------------
Every smart app is just the *generic* ``re-ddns/smart-launcher`` image started
with a different set of environment variables (GITHUB_REPO, APP_NAME, …).  The
container clones the repo, installs deps, registers DNS via re-ddns and starts
Reflex — all at runtime.  So installing an app = create + start one container
and watch its logs.

Progress is derived from the launcher's ``[smart-launcher] HH:MM:SS <stage>``
log markers plus Reflex's own ``App running`` line.

Endpoints (mounted under ``/api/appstore``)
    POST /api/appstore/install            → start an install job
    GET  /api/appstore/status             → progress of every known job
    GET  /api/appstore/status/{subdomain} → progress of one job
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import logging
import os
import re
import tarfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("re-ddns.install")

router = APIRouter(prefix="/api/appstore", tags=["appstore", "install"])

# Docker Engine API over the bind-mounted Unix socket.
DOCKER_SOCKET = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
# Generic launcher image shared by every smart app.
LAUNCHER_IMAGE = os.environ.get("SMART_LAUNCHER_IMAGE", "re-ddns/smart-launcher:latest")
# Build context for the launcher image (mounted read-only into re-ddns).
LAUNCHER_DIR = os.environ.get("SMART_LAUNCHER_DIR", "/app/smart_launcher")
# Max time to wait for an app to finish installing & report "App running".
INSTALL_TIMEOUT = int(os.environ.get("INSTALL_TIMEOUT", "900"))

# ---------------------------------------------------------------------------
# File-backed job store
# ---------------------------------------------------------------------------
# The re-ddns backend runs with multiple workers (like the registry), so the
# install progress MUST live in a shared file, not process memory.  The
# background install task runs in whichever worker accepted POST /install and
# writes progress here; any worker can serve GET /status by reading it.

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_STORE_PATH = _DATA_DIR / "install_jobs.json"

# Strip ANSI escape sequences and other control chars (Reflex/poetry emit them
# on the container PTY; they corrupt the JSON log field and are noise anyway).
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize(line: str) -> str:
    line = _ANSI_RE.sub("", line)
    line = _CTRL_RE.sub("", line)
    return line.rstrip()


@contextlib.contextmanager
def _locked_store(exclusive: bool):
    """Open the store file with an advisory flock (shared or exclusive)."""
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(_STORE_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        with os.fdopen(fd, "r+", encoding="utf-8") as fh:
            try:
                fh.seek(0)
                raw = fh.read()
                data = json.loads(raw) if raw.strip() else {}
            except (ValueError, OSError):
                data = {}
            yield fh, data
            fd = -1  # fdopen took ownership
    finally:
        if fd >= 0:
            os.close(fd)


def _write_store(fh, data: dict[str, Any]) -> None:
    fh.seek(0)
    fh.truncate()
    json.dump(data, fh, ensure_ascii=False)
    fh.flush()
    os.fsync(fh.fileno())


def _set_job(subdomain: str, **fields: Any) -> None:
    with _locked_store(exclusive=True) as (fh, data):
        job = data.setdefault(subdomain, {"subdomain": subdomain, "log": []})
        if "percent" in fields:
            prev = job.get("_max_percent", 0)
            fields["percent"] = max(prev, int(fields["percent"]))
            job["_max_percent"] = fields["percent"]
        job.update(fields)
        _write_store(fh, data)


def _append_log(subdomain: str, line: str) -> None:
    line = _sanitize(line)
    if not line:
        return
    with _locked_store(exclusive=True) as (fh, data):
        job = data.setdefault(subdomain, {"subdomain": subdomain, "log": []})
        log = job.setdefault("log", [])
        log.append(line)
        if len(log) > 80:
            del log[: len(log) - 80]
        _write_store(fh, data)


def get_job(subdomain: str) -> dict[str, Any] | None:
    with _locked_store(exclusive=False) as (_fh, data):
        job = data.get(subdomain)
        if job is None:
            return None
        return {k: v for k, v in job.items() if not k.startswith("_")}


def get_all_jobs() -> list[dict[str, Any]]:
    with _locked_store(exclusive=False) as (_fh, data):
        return [
            {k: v for k, v in job.items() if not k.startswith("_")}
            for job in data.values()
        ]


# ---------------------------------------------------------------------------
# Log marker → progress mapping
# ---------------------------------------------------------------------------

# (substring, phase, percent).  First match (top-down on each new line) wins
# for setting the phase; percent only ever increases.
_MARKERS: list[tuple[str, str, int]] = [
    ("Smart Launcher Configuration", "starting_container", 25),
    ("Installing extra APT packages", "apt_packages", 28),
    ("Cloning", "cloning", 32),
    ("Checking out commit", "cloning", 36),
    ("Installing project APT packages", "apt_packages", 40),
    ("Installing dependencies with Poetry", "installing_deps", 45),
    ("Running poetry lock", "installing_deps", 50),
    ("Running poetry install", "installing_deps", 58),
    ("Poetry install completed", "installing_deps", 70),
    ("Installing extra pip packages", "installing_deps", 72),
    ("Running reflex init", "initializing", 78),
    ("Running database migrations", "initializing", 82),
    ("Registering DNS record", "registering", 86),
    ("Starting Reflex dev server", "starting_app", 92),
    ("App running at", "running", 100),
    ("App running", "running", 100),
]

_PHASE_LABEL = {
    "queued": "排隊中",
    "preparing_image": "準備啟動器映像檔",
    "building_image": "建置啟動器映像檔",
    "creating": "建立容器",
    "starting_container": "啟動容器",
    "apt_packages": "安裝系統套件",
    "cloning": "下載程式碼",
    "installing_deps": "安裝相依套件",
    "initializing": "初始化 Reflex",
    "registering": "註冊 DNS / nginx",
    "starting_app": "啟動應用程式",
    "running": "完成，應用程式執行中",
    "error": "安裝失敗",
}


def _phase_from_line(line: str) -> tuple[str, int] | None:
    for substr, phase, percent in _MARKERS:
        if substr in line:
            return phase, percent
    return None


# ---------------------------------------------------------------------------
# Docker Engine API helpers (async, over the Unix socket)
# ---------------------------------------------------------------------------

def _client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
    return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=60.0)


async def _docker_network_name() -> str:
    """Return the Docker network re-ddns itself is attached to.

    This avoids hard-coding the compose project prefix (e.g.
    ``re_ddns_ddns-net``).  Falls back to ``ddns-net``.
    """
    try:
        async with _client() as c:
            r = await c.get("/containers/re-ddns/json")
            if r.status_code == 200:
                nets = r.json().get("NetworkSettings", {}).get("Networks", {})
                for name in nets:
                    if "ddns-net" in name:
                        return name
                if nets:
                    return next(iter(nets))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not discover docker network: %s", exc)
    return "ddns-net"


async def _image_exists(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(f"/images/{LAUNCHER_IMAGE}/json")
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _build_context_tar() -> bytes:
    """Tar the smart_launcher build context for the Docker /build endpoint."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name in ("Dockerfile", "entrypoint.sh", "register_dns.py"):
            path = os.path.join(LAUNCHER_DIR, name)
            if os.path.exists(path):
                tar.add(path, arcname=name)
    buf.seek(0)
    return buf.read()


async def _ensure_image(subdomain: str) -> bool:
    """Make sure the launcher image exists, building it if necessary."""
    async with _client() as client:
        if await _image_exists(client):
            return True

        _set_job(subdomain, phase="building_image", percent=8,
                 message="首次安裝：正在建置啟動器映像檔（約需數分鐘）…")
        _append_log(subdomain, "[install] Building launcher image (first run)…")

        context = _build_context_tar()
        if not context:
            _set_job(subdomain, status="error", phase="error",
                     message=f"找不到啟動器建置內容：{LAUNCHER_DIR}")
            return False

        try:
            async with client.stream(
                "POST",
                f"/build?t={LAUNCHER_IMAGE}&dockerfile=Dockerfile&rm=1",
                content=context,
                headers={"Content-Type": "application/x-tar"},
                timeout=None,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    _set_job(subdomain, status="error", phase="error",
                             message=f"映像檔建置失敗 (HTTP {resp.status_code})")
                    _append_log(subdomain, body.decode("utf-8", "ignore")[:500])
                    return False
                pct = 8
                async for chunk in resp.aiter_lines():
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    try:
                        evt = json.loads(chunk)
                    except ValueError:
                        continue
                    if "error" in evt:
                        _set_job(subdomain, status="error", phase="error",
                                 message=f"映像檔建置失敗：{evt['error'][:200]}")
                        return False
                    stream = evt.get("stream", "")
                    if stream.strip():
                        _append_log(subdomain, stream.rstrip())
                        if "Step " in stream and pct < 20:
                            pct += 1
                            _set_job(subdomain, percent=pct)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Image build failed")
            _set_job(subdomain, status="error", phase="error",
                     message=f"映像檔建置發生例外：{exc}")
            return False

        # Verify it now exists.
        if await _image_exists(client):
            _append_log(subdomain, "[install] Launcher image ready.")
            return True
        _set_job(subdomain, status="error", phase="error",
                 message="映像檔建置後仍找不到。")
        return False


async def _remove_existing_container(client: httpx.AsyncClient, name: str) -> None:
    """Stop + remove a container of the given name, ignoring 404."""
    try:
        await client.post(f"/containers/{name}/stop?t=5")
    except Exception:  # noqa: BLE001
        pass
    try:
        await client.delete(f"/containers/{name}?force=true")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Install request model
# ---------------------------------------------------------------------------

class InstallRequest(BaseModel):
    """Full spec for an app to install (mirrors a catalog entry)."""
    subdomain: str
    github_repo: str
    app_name: str
    name: str = ""              # display name
    branch: str = "main"
    commit: str = ""
    subdir: str = ""
    zone: str = "reflex-ddns.com"
    volumes: list[str] = []     # ["/host:/container", ...]
    env_file: str = ""          # host path mounted to /app/injected.env
    env: dict[str, str] = {}    # user-supplied app settings (e.g. API keys)


def _container_name(subdomain: str) -> str:
    return f"smart-app-{subdomain}"


def _build_env(req: InstallRequest) -> list[str]:
    env = [
        f"GITHUB_REPO={req.github_repo}",
        f"APP_NAME={req.app_name}",
        f"GITHUB_BRANCH={req.branch or 'main'}",
        f"GITHUB_COMMIT={req.commit or ''}",
        f"GITHUB_SUBDIR={req.subdir or ''}",
        f"SERVICE_SUBDOMAIN={req.subdomain}",
        f"SERVICE_ZONE={req.zone or 'reflex-ddns.com'}",
        "RE_DDNS_API_URL=http://re-ddns:8000",
        "REFLEX_FRONTEND_HOST=0.0.0.0",
        "REFLEX_BACKEND_HOST=0.0.0.0",
    ]
    # User-supplied app settings (e.g. LiveKit / Google OAuth credentials).
    # These are injected as real container env vars AND their names are passed
    # via ENV_FILE_VARS so the launcher also persists them into the app's .env.
    user_keys: list[str] = []
    for key, value in (req.env or {}).items():
        key = str(key).strip()
        if not key or "=" in key:
            continue  # skip malformed keys (env var names can't contain '=')
        env.append(f"{key}={value}")
        user_keys.append(key)
    if user_keys:
        env.append("ENV_FILE_VARS=" + " ".join(user_keys))
    return env


# ---------------------------------------------------------------------------
# Install: poll-driven state machine
# ---------------------------------------------------------------------------
# We deliberately AVOID a long-lived background asyncio task: the re-ddns
# backend runs under ``reflex run --env dev`` whose hot-reloader can restart
# the worker mid-install (it does so right when the new app registers itself),
# silently killing any background task.  Instead:
#   • POST /install            → create + start the container (fast) and record
#                                the job (status=installing, cid, seen=0).
#   • GET  /status/{subdomain} → advance the log scan by one step each time the
#                                UI polls, persisting progress to the file.
# All state lives in the shared file, so progress survives worker reloads.


async def _create_and_start(req: InstallRequest) -> None:
    """Ensure the image, then create + start the smart-app container."""
    sub = req.subdomain
    name = _container_name(sub)
    display = req.name or sub

    if not await _ensure_image(sub):
        return  # error state already set

    network = await _docker_network_name()
    async with _client() as client:
        _set_job(sub, phase="creating", percent=22, message=f"建立 {display} 容器…")
        await _remove_existing_container(client, name)

        binds: list[str] = list(req.volumes or [])
        if req.env_file and os.path.exists(req.env_file):
            binds.append(f"{req.env_file}:/app/injected.env:ro")

        config: dict[str, Any] = {
            "Image": LAUNCHER_IMAGE,
            "Hostname": name,
            "Tty": True,  # merge stdout/stderr → easy raw log parsing
            "Env": _build_env(req),
            "HostConfig": {
                "NetworkMode": network,
                "RestartPolicy": {"Name": "unless-stopped"},
            },
        }
        if binds:
            config["HostConfig"]["Binds"] = binds

        create = await client.post(f"/containers/create?name={name}", json=config)
        if create.status_code != 201:
            _set_job(sub, status="error", phase="error",
                     message=f"建立容器失敗 (HTTP {create.status_code})")
            return
        cid = create.json()["Id"]

        start = await client.post(f"/containers/{cid}/start")
        if start.status_code not in (204, 304):
            _set_job(sub, status="error", phase="error",
                     message=f"啟動容器失敗 (HTTP {start.status_code})")
            return

        _set_job(sub, status="installing", phase="starting_container", percent=25,
                 message=f"{display} 安裝中…", container=name, cid=cid, seen=0)


async def _advance(sub: str) -> None:
    """Read new container log output once and update the job's progress.

    Idempotent and safe to call from any worker on every status poll.
    """
    job = get_job(sub)
    if not job or job.get("status") != "installing":
        return
    cid = job.get("cid")
    if not cid:
        return
    display = job.get("name", sub)
    seen = int(job.get("seen", 0))
    tail = list(job.get("log", []))

    async with _client() as client:
        # 1) Fetch the *full* logs (Tty=true → raw text, no stream framing).
        try:
            r = await client.get(f"/containers/{cid}/logs?stdout=1&stderr=1")
            text = r.content.decode("utf-8", "ignore") if r.status_code == 200 else ""
        except Exception:  # noqa: BLE001
            text = ""

        best: tuple[str, int] | None = None
        reached_running = False
        if len(text) > seen:
            chunk = text[seen:]
            nl = chunk.rfind("\n")  # process only complete lines
            if nl >= 0:
                ready = chunk[: nl + 1]
                seen += len(ready)
                for raw in ready.splitlines():
                    line = _sanitize(raw)
                    if not line:
                        continue
                    tail.append(line)
                    mapped = _phase_from_line(line)
                    if mapped:
                        best = mapped
                        if mapped[0] == "running":
                            reached_running = True
                            break
                if len(tail) > 14:
                    del tail[: len(tail) - 14]

        if reached_running:
            _set_job(sub, status="installed", phase="running", percent=100, seen=seen,
                     message=f"{display} 安裝完成，已啟動！", log=tail)
            return
        if best is not None:
            phase, percent = best
            _set_job(sub, phase=phase, percent=percent, seen=seen,
                     message=f"{display}：{_PHASE_LABEL.get(phase, phase)}", log=tail)
        else:
            _set_job(sub, seen=seen, log=tail)

        # Did the container die before reporting success?
        try:
            insp = await client.get(f"/containers/{cid}/json")
            if insp.status_code == 200:
                state = insp.json().get("State", {})
                if not state.get("Running", False) and state.get("Status") in ("exited", "dead"):
                    _set_job(sub, status="error", phase="error",
                             message=f"{display} 容器已結束 (exit code {state.get('ExitCode', 0)})。")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class InstallStarted(BaseModel):
    ok: bool
    subdomain: str
    message: str


@router.post("/install", response_model=InstallStarted)
async def install_endpoint(req: InstallRequest):
    """Create + start the app container.  Poll /status to follow progress."""
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(503, "Docker socket not available in re-ddns container.")
    if not req.subdomain or not req.github_repo or not req.app_name:
        raise HTTPException(400, "subdomain, github_repo and app_name are required.")

    # Reset job state for a clean (re)install.
    with _locked_store(exclusive=True) as (fh, data):
        data[req.subdomain] = {
            "subdomain": req.subdomain,
            "name": req.name or req.subdomain,
            "status": "installing",
            "phase": "queued",
            "percent": 2,
            "_max_percent": 2,
            "message": "排隊中…",
            "log": [],
            "container": _container_name(req.subdomain),
            "seen": 0,
        }
        _write_store(fh, data)

    try:
        await _create_and_start(req)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Install of %s failed to start", req.subdomain)
        _set_job(req.subdomain, status="error", phase="error",
                 message=f"安裝啟動失敗：{exc}")

    logger.info("Install container started for %s", req.subdomain)
    return InstallStarted(ok=True, subdomain=req.subdomain, message="安裝已開始。")


@router.get("/status")
async def status_all():
    """Progress of every install job (advancing any in-flight ones)."""
    for job in get_all_jobs():
        if job.get("status") == "installing":
            try:
                await _advance(job["subdomain"])
            except Exception:  # noqa: BLE001
                logger.exception("advance failed for %s", job.get("subdomain"))
    return {"jobs": get_all_jobs()}


@router.get("/status/{subdomain}")
async def status_one(subdomain: str):
    """Progress of a single install job (404 if never started)."""
    job = get_job(subdomain)
    if job is None:
        raise HTTPException(404, f"No install job for '{subdomain}'.")
    if job.get("status") == "installing":
        try:
            await _advance(subdomain)
        except Exception:  # noqa: BLE001
            logger.exception("advance failed for %s", subdomain)
        job = get_job(subdomain) or job
    return job
