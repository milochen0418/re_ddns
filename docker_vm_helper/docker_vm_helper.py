#!/usr/bin/env python3
"""Docker VM memory helper: lets the App Store's Memory page resize the Docker VM.

Every app runs inside Docker Desktop's Linux VM, whose memory is fixed when the
VM starts (``com.docker.virtualization --memoryMiB 8192``).  Changing it means
changing Docker Desktop's setting and restarting the VM, which is what
*Settings → Resources → Apply & restart* does.  The App Store cannot do that
itself: it runs inside the VM, and Docker Desktop's settings API is a Unix
socket on the Mac (``~/Library/Containers/com.docker.docker/Data/backend.sock``)
that Docker Desktop will not mount into a container.

This small server runs on the Mac as a LaunchAgent (installed by
``macos_docker_vm_helper.sh --install``) and does that one job:

  GET  /vm                          the VM's memory setting, the range Docker
                                    Desktop allows, the Mac's RAM, and the
                                    last change
  POST /vm  {"memory_mib": 12288}   save a new size; Docker Desktop restarts
                                    its VM to apply it, which stops every
                                    container for a minute or two (those with
                                    a restart policy come back by themselves)

It sends the change to the same endpoint Docker Desktop's Settings window uses
(``POST /app/settings/gui``), so Docker Desktop checks the value and restarts
the VM itself.  The helper then watches the engine until the VM is back with
the new size; should the VM not restart within a minute, it runs
``docker desktop restart``.

It listens on 127.0.0.1 only; containers reach it as
``http://host.docker.internal:<port>``, which Docker Desktop forwards to the
Mac's loopback.  Since any container can do that, every request must carry the
token from ``~/.re_ddns/docker-vm-helper.json`` (created on first start, mode
600).  The App Store reads that file through its read-only mount of the home
folder; apps have no such mount.

Standard library only, so the system ``/usr/bin/python3`` (3.9) can run it.
"""

from __future__ import annotations

import hmac
import http.client
import http.server
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("DOCKER_VM_HELPER_CONFIG") or HOME / ".re_ddns" / "docker-vm-helper.json")
DEFAULT_PORT = 3143
TOKEN_HEADER = "X-Docker-VM-Helper-Token"

# Docker Desktop's own API (what its Settings window talks to), and the Docker
# Engine, to see the VM go down and come back with the new size.
BACKEND_SOCK = HOME / "Library" / "Containers" / "com.docker.docker" / "Data" / "backend.sock"
ENGINE_SOCKS = (Path("/var/run/docker.sock"), HOME / ".docker" / "run" / "docker.sock")
DOCKER_CLI = "/Applications/Docker.app/Contents/Resources/bin/docker"

MEMORY_KEY = "vm.resources.memoryMiB"
MIB = 1024 * 1024

# Seconds Docker Desktop gets to come back with the new size.
RESTART_TIMEOUT = 300
# Docker Desktop restarts the VM by itself once the setting is saved; if the
# engine is still up with the old size this many seconds later, ask it to.
NUDGE_AFTER = 60


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Docker Desktop and the engine
# ---------------------------------------------------------------------------

class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a Unix socket."""

    def __init__(self, path: Path, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = str(path)

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


def _call(sock: Path, method: str, path: str, body=None, timeout: float = 10.0):
    """One JSON request over ``sock``; the parsed reply, or an exception."""
    conn = _UnixHTTPConnection(sock, timeout)
    try:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if data is not None else {}
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()
    if resp.status >= 300:
        detail = raw[:200].decode(errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {resp.status} {detail}")
    return json.loads(raw) if raw.strip() else None


def desktop_memory() -> tuple[int, int, int]:
    """``(value, min, max)`` of the VM's memory in MiB, as Docker Desktop's Settings show them."""
    gui = _call(BACKEND_SOCK, "GET", "/app/settings/gui")
    value = int(gui["settings"][MEMORY_KEY])
    meta = (gui.get("metadata") or {}).get(MEMORY_KEY) or {}
    return value, int(meta.get("min") or 1024), int(meta.get("max") or value)


def engine_memtotal() -> int:
    """The running VM's MemTotal in bytes, or 0 while the engine is down."""
    for sock in ENGINE_SOCKS:
        if not sock.exists():
            continue
        try:
            return int((_call(sock, "GET", "/info", timeout=5.0) or {}).get("MemTotal") or 0)
        except Exception:  # noqa: BLE001 - down or restarting; try the other socket
            continue
    return 0


def host_mib() -> int:
    """The Mac's physical memory in MiB."""
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        return int(out.strip()) // MIB
    except Exception:  # noqa: BLE001 - only the page's hints need it
        return 0


# ---------------------------------------------------------------------------
# A change of size
# ---------------------------------------------------------------------------

class Busy(Exception):
    """A change is still being applied."""


_lock = threading.Lock()
# The last change: state (restarting | done | error), from_mib, to_mib, error,
# started, finished.  Kept in memory: it only has to outlive the VM restart,
# and this process runs on the Mac, outside the VM.
_job: dict = {}


def start_change(to_mib: int) -> dict:
    """Save the new size, then follow the restart in a thread."""
    with _lock:
        if _job.get("state") == "restarting":
            raise Busy("the previous change is still being applied")
        value, lo, hi = desktop_memory()
        if not lo <= to_mib <= hi:
            raise ValueError(f"memory_mib must be between {lo} and {hi}")
        if to_mib == value:
            return {"state": "unchanged", "from_mib": value, "to_mib": to_mib}
        before = engine_memtotal()
        _call(
            BACKEND_SOCK, "POST", "/app/settings/gui",
            {"settings": {MEMORY_KEY: to_mib}}, timeout=30.0,
        )
        _job.clear()
        _job.update(
            state="restarting", from_mib=value, to_mib=to_mib, error="",
            started=time.time(), finished=0.0,
        )
        log(f"memory {value} -> {to_mib} MiB saved; Docker Desktop restarts the VM")
        job = dict(_job)
    threading.Thread(target=_follow, args=(before, job["started"]), daemon=True).start()
    return job


def _follow(before: int, started: float) -> None:
    """Wait until the engine answers with a different MemTotal than ``before``."""
    went_down = nudged = False
    while time.time() - started < RESTART_TIMEOUT:
        time.sleep(2)
        total = engine_memtotal()
        if not total:
            went_down = True
            continue
        if total != before:
            log(f"the VM is back with {total // MIB} MiB")
            _finish("done", "")
            return
        if not went_down and not nudged and time.time() - started > NUDGE_AFTER:
            nudged = True
            log("the VM did not restart by itself; running docker desktop restart")
            try:
                subprocess.run(
                    [DOCKER_CLI, "desktop", "restart", "--detach"],
                    capture_output=True, timeout=60,
                )
            except Exception as exc:  # noqa: BLE001 - the timeout below reports it
                log(f"docker desktop restart failed: {exc}")
    error = f"Docker did not come back with the new size within {RESTART_TIMEOUT // 60} minutes"
    log(error)
    _finish("error", error)


def _finish(state: str, error: str) -> None:
    with _lock:
        _job.update(state=state, error=error, finished=time.time())


def vm_info() -> dict:
    value, lo, hi = desktop_memory()
    with _lock:
        job = dict(_job)
    if job:
        # Seconds since the change ended (or began), so the page needs no clock.
        job["age"] = int(time.time() - (job.get("finished") or job["started"]))
    return {
        "memory_mib": value, "min_mib": lo, "max_mib": hi,
        "host_mib": host_mib(), "job": job,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "docker-vm-helper/1"
    token = ""

    def log_message(self, format, *args):  # noqa: A002 - only changes and errors are logged
        pass

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self) -> bool:
        if self.path.split("?", 1)[0] != "/vm":
            self._reply(404, {"error": "not found"})
            return False
        given = self.headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(given.encode(), self.token.encode()):
            self._reply(401, {"error": "missing or wrong token"})
            return False
        return True

    def do_GET(self):  # noqa: N802
        if not self._allowed():
            return
        try:
            self._reply(200, vm_info())
        except Exception as exc:  # noqa: BLE001
            self._reply(502, {"error": f"Docker Desktop: {exc}"})

    def do_POST(self):  # noqa: N802
        if not self._allowed():
            return
        to_mib = None
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            to_mib = json.loads(self.rfile.read(length) or b"{}").get("memory_mib")
            if isinstance(to_mib, bool) or not isinstance(to_mib, int):
                raise ValueError("memory_mib must be a whole number of MiB")
            reply = start_change(to_mib)
        except Busy as exc:
            self._reply(409, {"error": str(exc)})
        except (ValueError, AttributeError) as exc:
            self._reply(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            log(f"changing to {to_mib} MiB failed: {exc}")
            self._reply(502, {"error": f"Docker Desktop: {exc}"})
        else:
            self._reply(200, reply)


def load_config() -> dict:
    """``{"port", "token"}`` from CONFIG, writing whatever is missing."""
    try:
        cfg = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    if not cfg.get("port") or not cfg.get("token"):
        cfg["port"] = int(cfg.get("port") or DEFAULT_PORT)
        cfg["token"] = str(cfg.get("token") or secrets.token_hex(24))
        CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = CONFIG.with_name(CONFIG.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(cfg, indent=2) + "\n")
        os.replace(tmp, CONFIG)
    return cfg


def main() -> None:
    cfg = load_config()
    Handler.token = str(cfg["token"])
    port = int(cfg["port"])
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log(f"listening on 127.0.0.1:{port} (config {CONFIG})")
    server.serve_forever()


if __name__ == "__main__":
    main()
