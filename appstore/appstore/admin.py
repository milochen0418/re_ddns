"""The re-ddns admin token, for the App Store's calls that change the platform.

re-ddns asks for it on installs, uninstalls and every call of the storage
page (``re_ddns/api/admin_auth.py``).  It is ``RE_DDNS_ADMIN_TOKEN`` when that
is set here; otherwise re-ddns keeps a generated one in ``/app/data/admin_token``
inside its container, and the App Store reads that file through the Docker
socket it already holds (``GET /containers/re-ddns/archive``).  Nothing needs
configuring, and apps, which have no Docker socket, cannot read it.

The token is read once and kept; a 401 reads it again (re-ddns may have been
recreated with a new one) and retries once.
"""

from __future__ import annotations

import asyncio
import io
import os
import tarfile
import threading

import httpx

ADMIN_HEADER = "X-Re-DDNS-Admin-Token"
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
RE_DDNS_CONTAINER = os.environ.get("RE_DDNS_CONTAINER", "re-ddns")
TOKEN_PATH = os.environ.get("RE_DDNS_ADMIN_TOKEN_PATH", "/app/data/admin_token")

_lock = threading.Lock()
_token = ""


def _from_container() -> str:
    if not os.path.exists(DOCKER_SOCK):
        return ""
    try:
        transport = httpx.HTTPTransport(uds=DOCKER_SOCK)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=5.0) as client:
            r = client.get(f"/containers/{RE_DDNS_CONTAINER}/archive", params={"path": TOKEN_PATH})
        if r.status_code != 200:
            print(f"[appstore] re-ddns admin token: docker archive answered HTTP {r.status_code}")
            return ""
        # Only read the one regular file's bytes: nothing is extracted to disk.
        with tarfile.open(fileobj=io.BytesIO(r.content)) as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and m.size < 4096), None)
            fh = tar.extractfile(member) if member is not None else None
            return fh.read().decode("utf-8", "replace").strip() if fh is not None else ""
    except Exception as exc:  # noqa: BLE001
        print(f"[appstore] cannot read the re-ddns admin token: {exc}")
        return ""


def admin_token(refresh: bool = False) -> str:
    env = os.environ.get("RE_DDNS_ADMIN_TOKEN", "").strip()
    if env:
        return env
    global _token
    with _lock:
        if refresh or not _token:
            _token = _from_container()
        return _token


def admin_headers(refresh: bool = False) -> dict[str, str]:
    token = admin_token(refresh)
    return {ADMIN_HEADER: token} if token else {}


def admin_request(method: str, url: str, *, timeout: float = 30.0, **kwargs) -> httpx.Response:
    """A request to re-ddns with the admin token (read again and retried once on a 401)."""
    with httpx.Client(timeout=timeout) as client:
        r = client.request(method, url, headers=admin_headers(), **kwargs)
        if r.status_code == 401:
            r = client.request(method, url, headers=admin_headers(refresh=True), **kwargs)
    return r


async def admin_request_async(method: str, url: str, *, timeout: float = 30.0, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.request(method, url, headers=await asyncio.to_thread(admin_headers), **kwargs)
        if r.status_code == 401:
            headers = await asyncio.to_thread(admin_headers, True)
            r = await client.request(method, url, headers=headers, **kwargs)
    return r
