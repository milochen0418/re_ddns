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
    POST /api/appstore/uninstall          → start an uninstall job (same
                                            status endpoints follow it)
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import io
import json
import logging
import os
import posixpath
import re
import tarfile
import time
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
    ("DEV_MODE: using mounted source", "dev_mount", 32),
    ("Installing extra APT packages", "apt_packages", 28),
    ("Cloning", "cloning", 32),
    ("Checking out commit", "cloning", 36),
    ("Installing project APT packages", "apt_packages", 40),
    ("Cloning dependency repo", "cloning_deps", 43),
    ("Installing dependencies with Poetry", "installing_deps", 45),
    ("Running poetry lock", "installing_deps", 50),
    ("Running poetry install", "installing_deps", 58),
    ("Poetry install completed", "installing_deps", 70),
    ("Installing extra pip packages", "installing_deps", 72),
    ("Running reflex init", "initializing", 78),
    ("Running database migrations", "initializing", 82),
    ("Registering DNS record", "registering", 86),
    ("Starting Reflex dev server", "starting_app", 92),
    ("Starting Reflex prod server", "starting_app", 92),
    ("App running at", "running", 100),
    ("App running", "running", 100),
]

_PHASE_LABEL = {
    "queued": "排隊中",
    "preparing_image": "準備啟動器映像檔",
    "building_image": "建置啟動器映像檔",
    "creating": "建立容器",
    "starting_container": "啟動容器",
    "dev_mount": "使用本機掛載的原始碼",
    "apt_packages": "安裝系統套件",
    "cloning": "下載程式碼",
    "cloning_deps": "下載相依套件庫",
    "installing_deps": "安裝相依套件",
    "initializing": "初始化 Reflex",
    "registering": "註冊 DNS / nginx",
    "starting_app": "啟動應用程式",
    "running": "完成，應用程式執行中",
    "error": "安裝失敗",
}

# Job messages by key.  ``message`` keeps this (Chinese) text for anything that
# reads the API directly; ``msg`` + ``msg_args`` let the App Store show the
# message in the viewer's language.  Its i18n tables hold ``job_<key>`` for
# every key here, and ``phase_<phase>`` for the {phase} of "phase".
_MESSAGES: dict[str, str] = {
    "queued": "排隊中…",
    "queued_dev": "排隊中（開發模式）…",
    "building_image": "首次安裝：正在建置啟動器映像檔（約需數分鐘）…",
    "image_context_missing": "找不到啟動器建置內容：{path}",
    "image_build_http": "映像檔建置失敗 (HTTP {code})",
    "image_build_failed": "映像檔建置失敗：{error}",
    "image_build_exception": "映像檔建置發生例外：{error}",
    "image_missing": "映像檔建置後仍找不到。",
    "creating": "建立 {name} 容器…",
    "creating_dev": "建立 {name} 開發容器…",
    "create_failed": "建立容器失敗 (HTTP {code})",
    "start_failed": "啟動容器失敗 (HTTP {code})：{error}",
    "installing": "{name} 安裝中…",
    "installing_dev": "{name} 開發模式安裝中…",
    "phase": "{name}：{phase}",
    "installed": "{name} 安裝完成，已啟動！",
    "container_exited": "{name} 容器已結束 (exit code {code})。",
    "install_start_failed": "安裝啟動失敗：{error}",
    "dev_install_start_failed": "開發模式安裝啟動失敗：{error}",
    "stop_waiting": "{name}：等待容器結束…（{seconds} 秒）",
    "uninstalled": "{name} 已移除。",
    "uninstall_failed": "{name} 移除失敗：{error}",
}


def _msg(key: str, **args: Any) -> dict[str, Any]:
    """The message fields of a job update, e.g. ``**_msg("creating", name=x)``."""
    args = {k: str(v) for k, v in args.items()}
    shown = dict(args)
    if "phase" in shown:
        phase = shown["phase"]
        shown["phase"] = _PHASE_LABEL.get(phase) or _UNINSTALL_PHASE_LABEL.get(phase, phase)
    return {"message": _MESSAGES[key].format(**shown), "msg": key, "msg_args": args}


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
                 **_msg("building_image"))
        _append_log(subdomain, "[install] Building launcher image (first run)…")

        context = _build_context_tar()
        if not context:
            _set_job(subdomain, status="error", phase="error",
                     **_msg("image_context_missing", path=LAUNCHER_DIR))
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
                             **_msg("image_build_http", code=resp.status_code))
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
                                 **_msg("image_build_failed", error=evt["error"][:200]))
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
                     **_msg("image_build_exception", error=exc))
            return False

        # Verify it now exists.
        if await _image_exists(client):
            _append_log(subdomain, "[install] Launcher image ready.")
            return True
        _set_job(subdomain, status="error", phase="error",
                 **_msg("image_missing"))
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
    extra_repos: list[str] = [] # ["repo_url:relative_path", ...] for path deps
    ports: list[str] = []       # ["host:container[/udp]", ...] published on the host


class DevInstallRequest(BaseModel):
    """Spec for a dev-mode install: bind-mount local source instead of cloning."""
    subdomain: str
    app_name: str
    local_path: str             # absolute path on the Docker host
    name: str = ""
    subdir: str = ""
    zone: str = "reflex-ddns.com"
    volumes: list[str] = []
    env_file: str = ""
    env: dict[str, str] = {}
    extra_repos: list[str] = []
    ports: list[str] = []
    # Host path of the reflex_ddns_auth checkout to use instead of GitHub
    # (default: sibling of local_path, i.e. <parent>/reflex_ddns_auth).
    auth_lib_path: str = ""


# Where a dev container sees the host's reflex_ddns_auth checkout; the
# launcher links it in place of the GitHub clone when this path exists.
DEV_AUTH_LIB_TARGET = "/app/dev_libs/reflex_ddns_auth"


def _container_name(subdomain: str) -> str:
    return f"smart-app-{subdomain}"


# DDNS_AUTH_SECRET: shared SSO secret — relack signs the ddns_auth JWT with it,
#   other apps verify.
# EXTERNAL_IP: the Docker host's LAN IP (what the DNS records point to) — apps
#   that publish ports (e.g. WebRTC media) advertise it to browsers.
_SHARED_ENV_KEYS = ("DDNS_AUTH_SECRET", "EXTERNAL_IP")


def _shared_env(user_env: dict[str, str] | None) -> list[str]:
    return [
        f"{k}={os.environ[k]}"
        for k in _SHARED_ENV_KEYS
        if os.environ.get(k) and k not in (user_env or {})
    ]


def _port_bindings(ports: list[str]) -> tuple[dict[str, dict], dict[str, list[dict[str, str]]]]:
    """``["7882:7882/udp", "7881"]`` → Docker ``ExposedPorts`` + ``PortBindings``.

    Apps only need published ports for traffic nginx cannot proxy (e.g. the
    UDP/TCP media ports of a WebRTC server); HTTP still goes through nginx.
    """
    exposed: dict[str, dict] = {}
    bindings: dict[str, list[dict[str, str]]] = {}
    for spec in ports or []:
        mapping, _, proto = str(spec).strip().partition("/")
        host_port, _, container_port = mapping.rpartition(":")
        host_port = host_port or container_port
        if not (host_port.isdigit() and container_port.isdigit()):
            logger.warning("Ignoring invalid port spec %r", spec)
            continue
        key = f"{container_port}/{proto.lower() or 'tcp'}"
        exposed[key] = {}
        bindings.setdefault(key, []).append({"HostPort": host_port})
    return exposed, bindings


def _docker_error(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message", ""))[:200]
    except ValueError:
        return resp.text[:200]


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
        # Hide the fixed "Built with Reflex" badge Reflex adds in prod mode.
        "REFLEX_SHOW_BUILT_WITH_REFLEX=false",
        *_shared_env(req.env),
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
    if req.extra_repos:
        env.append("EXTRA_GIT_REPOS=" + " ".join(req.extra_repos))
    return env


def _build_dev_env(req: DevInstallRequest) -> list[str]:
    """Build container environment for a dev-mode install."""
    env = [
        "DEV_MODE=1",
        f"APP_NAME={req.app_name}",
        f"GITHUB_SUBDIR={req.subdir or ''}",
        f"SERVICE_SUBDOMAIN={req.subdomain}",
        f"SERVICE_ZONE={req.zone or 'reflex-ddns.com'}",
        "RE_DDNS_API_URL=http://re-ddns:8000",
        "REFLEX_FRONTEND_HOST=0.0.0.0",
        "REFLEX_BACKEND_HOST=0.0.0.0",
        # Hide the fixed "Built with Reflex" badge Reflex adds in prod mode.
        "REFLEX_SHOW_BUILT_WITH_REFLEX=false",
        *_shared_env(req.env),
    ]
    user_keys: list[str] = []
    for key, value in (req.env or {}).items():
        key = str(key).strip()
        if not key or "=" in key:
            continue
        env.append(f"{key}={value}")
        user_keys.append(key)
    if user_keys:
        env.append("ENV_FILE_VARS=" + " ".join(user_keys))
    if req.extra_repos:
        env.append("EXTRA_GIT_REPOS=" + " ".join(req.extra_repos))
    return env


async def _create_and_start_dev(req: DevInstallRequest) -> None:
    """Create + start a dev-mode container with the host source bind-mounted."""
    sub = req.subdomain
    name = _container_name(sub)
    display = req.name or sub

    if not await _ensure_image(sub):
        return

    network = await _docker_network_name()
    async with _client() as client:
        _set_job(sub, phase="creating", percent=22, **_msg("creating_dev", name=display))
        await _remove_existing_container(client, name)

        binds: list[str] = list(req.volumes or [])
        binds.append(f"{req.local_path}:/app/dev_src:rw")
        # The container's own runtime data (SQLite DBs) — kept apart from the
        # host copy, which SQLite cannot safely share across the VM boundary.
        binds.append(f"{name}-state:/app/dev_state")
        if req.env_file and os.path.exists(req.env_file):
            binds.append(f"{req.env_file}:/app/injected.env:ro")

        config: dict[str, Any] = {
            "Image": LAUNCHER_IMAGE,
            "Hostname": name,
            "Tty": True,
            "Env": _build_dev_env(req),
            "HostConfig": {
                "NetworkMode": network,
                "RestartPolicy": {"Name": "unless-stopped"},
                "Binds": binds,
            },
        }

        # Use the host's local reflex_ddns_auth (live edits) instead of the
        # GitHub copy.  A "Mounts" bind (unlike "Binds") fails instead of
        # creating an empty dir when the host path is missing — then we
        # retry without it and the launcher falls back to cloning GitHub.
        auth_lib = req.auth_lib_path or posixpath.join(
            posixpath.dirname(req.local_path.rstrip("/")), "reflex_ddns_auth")
        config["HostConfig"]["Mounts"] = [{
            "Type": "bind", "Source": auth_lib,
            "Target": DEV_AUTH_LIB_TARGET, "ReadOnly": True,
        }]
        exposed, bindings = _port_bindings(req.ports)
        if bindings:
            config["ExposedPorts"] = exposed
            config["HostConfig"]["PortBindings"] = bindings

        create = await client.post(f"/containers/create?name={name}", json=config)
        if create.status_code != 201 and "does not exist" in create.text:
            _append_log(sub, f"[install] {auth_lib} not found — "
                             "reflex_ddns_auth will come from GitHub")
            del config["HostConfig"]["Mounts"]
            create = await client.post(f"/containers/create?name={name}", json=config)
        if create.status_code != 201:
            _set_job(sub, status="error", phase="error",
                     **_msg("create_failed", code=create.status_code))
            return
        cid = create.json()["Id"]

        start = await client.post(f"/containers/{cid}/start")
        if start.status_code not in (204, 304):
            _set_job(sub, status="error", phase="error",
                     **_msg("start_failed", code=start.status_code, error=_docker_error(start)))
            return

        _set_job(sub, status="installing", phase="starting_container", percent=25,
                 **_msg("installing_dev", name=display), container=name, cid=cid, seen=0)


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
        _set_job(sub, phase="creating", percent=22, **_msg("creating", name=display))
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
        exposed, bindings = _port_bindings(req.ports)
        if bindings:
            config["ExposedPorts"] = exposed
            config["HostConfig"]["PortBindings"] = bindings

        create = await client.post(f"/containers/create?name={name}", json=config)
        if create.status_code != 201:
            _set_job(sub, status="error", phase="error",
                     **_msg("create_failed", code=create.status_code))
            return
        cid = create.json()["Id"]

        start = await client.post(f"/containers/{cid}/start")
        if start.status_code not in (204, 304):
            _set_job(sub, status="error", phase="error",
                     **_msg("start_failed", code=start.status_code, error=_docker_error(start)))
            return

        _set_job(sub, status="installing", phase="starting_container", percent=25,
                 **_msg("installing", name=display), container=name, cid=cid, seen=0)


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
                     **_msg("installed", name=display), log=tail)
            return
        if best is not None:
            phase, percent = best
            _set_job(sub, phase=phase, percent=percent, seen=seen,
                     **_msg("phase", name=display, phase=phase), log=tail)
        else:
            _set_job(sub, seen=seen, log=tail)

        # Did the container die before reporting success?
        try:
            insp = await client.get(f"/containers/{cid}/json")
            if insp.status_code == 200:
                state = insp.json().get("State", {})
                if not state.get("Running", False) and state.get("Status") in ("exited", "dead"):
                    _set_job(sub, status="error", phase="error",
                             **_msg("container_exited", name=display,
                                    code=state.get("ExitCode", 0)))
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Uninstall: poll-driven state machine
# ---------------------------------------------------------------------------
# Built like the install flow above, and for the same reason: the dev-mode hot
# reloader restarts this backend whenever something under /app changes, and an
# uninstall changes /app/data/registry.json half-way through.  A FastAPI
# background task dies with the worker (that is how containers were left
# behind "Stopped" after an uninstall), so instead every step here is short,
# idempotent and recorded in the shared job file.  A step is taken by whoever
# calls ``_advance_uninstall``: the App Store's status polls, and a small
# driver task started by the POST that keeps the job moving when nobody polls.
# A short lease in the job keeps two workers from running the same step.
#
#   queued → stopping → removing_container → unregistering → nginx → cert
#          → [data] → done

class UninstallRequest(BaseModel):
    subdomain: str
    name: str = ""              # display name
    zone: str = "reflex-ddns.com"
    remove_data: bool = False   # also delete the app's named Docker volumes


# Seconds a container gets to exit on its StopSignal before SIGKILL
# (``docker stop -t``); the container's own StopTimeout wins when it has one.
UNINSTALL_STOP_GRACE = int(os.environ.get("UNINSTALL_STOP_GRACE", "10"))
UNINSTALL_STOP_HARD = 30    # still running after this → remove with force=true
_LEASE_SECONDS = 20         # how long one worker owns a step

_UNINSTALL_PHASE_LABEL = {
    "queued": "排隊中",
    "stopping": "停止容器",
    "removing_container": "刪除容器",
    "unregistering": "移除註冊與 DNS 記錄",
    "nginx": "更新 nginx 設定",
    "cert": "移除 TLS 憑證",
    "data": "刪除資料 volume",
    "done": "完成，已移除",
    "error": "移除失敗",
}


def _take_lease(sub: str) -> dict[str, Any] | None:
    """Claim the next uninstall step for this worker (None: not ours to take)."""
    now = time.time()
    with _locked_store(exclusive=True) as (fh, data):
        job = data.get(sub)
        if not job or job.get("status") != "uninstalling":
            return None
        if float(job.get("_lease", 0)) > now:
            return None
        job["_lease"] = now + _LEASE_SECONDS
        _write_store(fh, data)
        return dict(job)


def _uninstall_phase(sub: str, display: str, phase: str, percent: int, **extra: Any) -> None:
    _set_job(sub, phase=phase, percent=percent,
             **_msg("phase", name=display, phase=phase), **extra)


async def _request_stop(client: httpx.AsyncClient, name: str, grace: int) -> None:
    """Ask Docker to stop a container without waiting for it.

    ``POST /stop`` blocks until the container is down; a short client timeout
    turns it into fire-and-forget.  The daemon finishes the stop on its own
    (StopSignal now, SIGKILL after the grace period) and marks the container
    as stopped on purpose, so its restart policy does not bring it back.  The
    following polls watch the container state instead of waiting here.
    """
    try:
        await client.post(f"/containers/{name}/stop?t={grace}", timeout=2.0)
    except httpx.TimeoutException:
        pass


def _volume_names(info: dict[str, Any]) -> list[str]:
    """Named Docker volumes a container mounts (bind mounts are not data)."""
    return sorted({
        m["Name"] for m in info.get("Mounts", [])
        if m.get("Type") == "volume" and m.get("Name")
    })


async def _uninstall_step(sub: str, job: dict[str, Any]) -> None:
    """Run one step of an uninstall and record the phase that follows."""
    from re_ddns.api import cert_manager, dns_manager, nginx_manager, registry_api

    phase = job.get("phase", "queued")
    name = job.get("container") or _container_name(sub)
    display = job.get("name") or sub
    zone = job.get("zone") or "reflex-ddns.com"
    fqdn = f"{sub}.{zone}"

    if phase in ("queued", "stopping"):
        async with _client() as client:
            insp = await client.get(f"/containers/{name}/json")
            if insp.status_code == 404:
                _append_log(sub, f"[uninstall] Container {name} does not exist; nothing to stop.")
                _uninstall_phase(sub, display, "unregistering", 55)
                return
            if insp.status_code != 200:
                raise RuntimeError(f"inspect {name}: HTTP {insp.status_code} {_docker_error(insp)}")
            info = insp.json()
            state = info.get("State", {})
            status = state.get("Status", "")
            alive = status in ("running", "paused", "restarting")

            if phase == "queued":
                volumes = _volume_names(info)
                if not alive:
                    _append_log(sub, f"[uninstall] Container {name} is already {status}.")
                    _uninstall_phase(sub, display, "removing_container", 35, _volumes=volumes)
                    return
                config = info.get("Config", {})
                grace = int(config.get("StopTimeout") or UNINSTALL_STOP_GRACE)
                signal = config.get("StopSignal") or "SIGTERM"
                _append_log(sub, f"[uninstall] Stopping container {name} "
                                 f"({signal}, SIGKILL after {grace}s)…")
                _uninstall_phase(sub, display, "stopping", 10, _volumes=volumes,
                                 _stop_started=time.time(), _stop_grace=grace)
                await _request_stop(client, name, grace)
                return

            # phase == "stopping": wait for the container to go down.
            if not alive:
                _append_log(sub, f"[uninstall] Container exited (code {state.get('ExitCode', 0)}).")
                _uninstall_phase(sub, display, "removing_container", 35)
                return
            waited = time.time() - float(job.get("_stop_started") or time.time())
            if waited > UNINSTALL_STOP_HARD:
                _append_log(sub, f"[uninstall] Still {status} after {int(waited)}s; removing by force.")
                _uninstall_phase(sub, display, "removing_container", 35)
                return
            grace = int(job.get("_stop_grace") or UNINSTALL_STOP_GRACE)
            if waited > grace + 3 and not job.get("_stop_resent"):
                # The daemon should have escalated to SIGKILL by now; ask again
                # in case the first request never reached it.
                _append_log(sub, "[uninstall] Container still up; sending stop again.")
                _set_job(sub, _stop_resent=True)
                await _request_stop(client, name, 2)
            _set_job(sub, percent=min(30, 10 + int(waited * 2)),
                     **_msg("stop_waiting", name=display, seconds=int(waited)))
            return

    if phase == "removing_container":
        anon = "true" if job.get("remove_data") else "false"
        async with _client() as client:
            r = await client.delete(f"/containers/{name}?force=true&v={anon}", timeout=60.0)
        if r.status_code == 204:
            _append_log(sub, f"[uninstall] Removed container {name}.")
        elif r.status_code == 404:
            _append_log(sub, f"[uninstall] Container {name} was already gone.")
        else:
            raise RuntimeError(f"remove {name}: HTTP {r.status_code} {_docker_error(r)}")
        _uninstall_phase(sub, display, "unregistering", 55)
        return

    if phase == "unregistering":
        svc = registry_api.get_service(sub)
        if registry_api.delete_service(sub):
            if svc and svc.get("zone"):
                zone = svc["zone"]
                fqdn = f"{sub}.{zone}"
            _append_log(sub, f"[uninstall] Removed {sub} from the service registry.")
        else:
            _append_log(sub, f"[uninstall] {sub} was not in the service registry.")
        ok, msg = await asyncio.to_thread(dns_manager.do_dns_delete, sub, zone)
        if ok:
            _append_log(sub, f"[uninstall] DNS record {fqdn} deleted.")
        else:
            _append_log(sub, f"[uninstall] WARNING: DNS delete failed: {msg}")
        _uninstall_phase(sub, display, "nginx", 70, zone=zone)
        return

    if phase == "nginx":
        try:
            ok = await asyncio.to_thread(nginx_manager.sync)
        except Exception:  # noqa: BLE001
            logger.exception("nginx sync failed while uninstalling %s", sub)
            ok = False
        if ok:
            _append_log(sub, f"[uninstall] nginx config for {fqdn} removed; nginx reloaded.")
        else:
            _append_log(sub, "[uninstall] WARNING: nginx reload failed (see the re-ddns log).")
        _uninstall_phase(sub, display, "cert", 82)
        return

    if phase == "cert":
        if await asyncio.to_thread(cert_manager.remove_cert, fqdn):
            _append_log(sub, f"[uninstall] TLS certificate for {fqdn} removed.")
        else:
            _append_log(sub, f"[uninstall] No TLS certificate for {fqdn} to remove.")
        volumes = list(job.get("_volumes") or [])
        if volumes and job.get("remove_data"):
            _uninstall_phase(sub, display, "data", 90)
            return
        if volumes:
            _append_log(sub, "[uninstall] Kept data volume(s): " + ", ".join(volumes)
                             + " (a reinstall uses them again).")
        _finish_uninstall(sub, display)
        return

    if phase == "data":
        async with _client() as client:
            for vol in job.get("_volumes") or []:
                r = await client.delete(f"/volumes/{vol}?force=true", timeout=60.0)
                if r.status_code == 204:
                    _append_log(sub, f"[uninstall] Removed volume {vol}.")
                elif r.status_code == 404:
                    _append_log(sub, f"[uninstall] Volume {vol} was already gone.")
                else:
                    _append_log(sub, f"[uninstall] WARNING: could not remove volume {vol}: "
                                     f"HTTP {r.status_code} {_docker_error(r)}")
        _finish_uninstall(sub, display)
        return

    # A phase this version does not know (job written by another version).
    _finish_uninstall(sub, display)


def _finish_uninstall(sub: str, display: str) -> None:
    _append_log(sub, f"[uninstall] {display} removed.")
    _set_job(sub, status="uninstalled", phase="done", percent=100,
             **_msg("uninstalled", name=display))


async def _advance_uninstall(sub: str) -> None:
    """Take one uninstall step, if the job is in flight and nobody else is on it."""
    job = _take_lease(sub)
    if job is None:
        return
    try:
        await _uninstall_step(sub, job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Uninstall step failed for %s", sub)
        _append_log(sub, f"[uninstall] ERROR: {exc}")
        _set_job(sub, status="error", phase="error",
                 **_msg("uninstall_failed", name=job.get("name") or sub, error=exc))
    finally:
        _set_job(sub, _lease=0)


_driver_tasks: set[asyncio.Task] = set()


def _start_uninstall_driver(sub: str) -> None:
    """Keep an uninstall moving even when nobody polls its status."""

    async def drive() -> None:
        deadline = time.time() + UNINSTALL_STOP_HARD + 90
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            job = get_job(sub)
            if not job or job.get("status") != "uninstalling":
                return
            await _advance_uninstall(sub)

    task = asyncio.get_running_loop().create_task(drive())
    _driver_tasks.add(task)
    task.add_done_callback(_driver_tasks.discard)


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
            "kind": "install",
            "status": "installing",
            "phase": "queued",
            "percent": 2,
            "_max_percent": 2,
            **_msg("queued"),
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
                 **_msg("install_start_failed", error=exc))

    logger.info("Install container started for %s", req.subdomain)
    return InstallStarted(ok=True, subdomain=req.subdomain, message="安裝已開始。")


@router.get("/status")
async def status_all():
    """Progress of every install job (advancing any in-flight ones)."""
    for job in get_all_jobs():
        try:
            if job.get("status") == "installing":
                await _advance(job["subdomain"])
            elif job.get("status") == "uninstalling":
                await _advance_uninstall(job["subdomain"])
        except Exception:  # noqa: BLE001
            logger.exception("advance failed for %s", job.get("subdomain"))
    return {"jobs": get_all_jobs()}


@router.get("/status/{subdomain}")
async def status_one(subdomain: str):
    """Progress of a single install job (404 if never started)."""
    job = get_job(subdomain)
    if job is None:
        raise HTTPException(404, f"No install job for '{subdomain}'.")
    try:
        if job.get("status") == "installing":
            await _advance(subdomain)
        elif job.get("status") == "uninstalling":
            await _advance_uninstall(subdomain)
    except Exception:  # noqa: BLE001
        logger.exception("advance failed for %s", subdomain)
    return get_job(subdomain) or job


@router.post("/dev-install", response_model=InstallStarted)
async def dev_install_endpoint(req: DevInstallRequest):
    """Dev mode: mount local source into a container instead of cloning."""
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(503, "Docker socket not available in re-ddns container.")
    if not req.subdomain or not req.app_name or not req.local_path:
        raise HTTPException(400, "subdomain, app_name and local_path are required.")

    with _locked_store(exclusive=True) as (fh, data):
        data[req.subdomain] = {
            "subdomain": req.subdomain,
            "name": req.name or req.subdomain,
            "kind": "install",
            "status": "installing",
            "phase": "queued",
            "percent": 2,
            "_max_percent": 2,
            **_msg("queued_dev"),
            "log": [],
            "container": _container_name(req.subdomain),
            "seen": 0,
            "dev_mode": True,
        }
        _write_store(fh, data)

    try:
        await _create_and_start_dev(req)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dev install of %s failed to start", req.subdomain)
        _set_job(req.subdomain, status="error", phase="error",
                 **_msg("dev_install_start_failed", error=exc))

    logger.info("Dev install container started for %s (local_path=%s)", req.subdomain, req.local_path)
    return InstallStarted(ok=True, subdomain=req.subdomain, message="開發模式安裝已開始。")


@router.post("/uninstall", response_model=InstallStarted)
async def uninstall_endpoint(req: UninstallRequest):
    """Remove an app: container, then registry + DNS + nginx + TLS records.

    Returns at once; poll /status/{subdomain} to follow the steps.  A job
    already in flight for the same app is left alone.
    """
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(503, "Docker socket not available in re-ddns container.")
    sub = req.subdomain.strip()
    if not sub:
        raise HTTPException(400, "subdomain is required.")

    with _locked_store(exclusive=True) as (fh, data):
        if (data.get(sub) or {}).get("status") == "uninstalling":
            return InstallStarted(ok=True, subdomain=sub, message="移除已在進行中。")
        data[sub] = {
            "subdomain": sub,
            "name": req.name or sub,
            "kind": "uninstall",
            "status": "uninstalling",
            "phase": "queued",
            "percent": 2,
            "_max_percent": 2,
            **_msg("queued"),
            "log": [],
            "container": _container_name(sub),
            "zone": req.zone or "reflex-ddns.com",
            "remove_data": bool(req.remove_data),
        }
        _write_store(fh, data)

    # First step right away, so the reply already reflects real progress.
    await _advance_uninstall(sub)
    _start_uninstall_driver(sub)
    logger.info("Uninstall started for %s (remove_data=%s)", sub, req.remove_data)
    return InstallStarted(ok=True, subdomain=sub, message="移除已開始。")
