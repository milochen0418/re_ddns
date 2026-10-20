"""Admin token: who may change the platform, not just use it.

Every app container reaches re-ddns over the Docker network, and every
machine on the LAN reaches it through nginx (``home.<zone>``).  So the
endpoints that install or remove apps, or that delete, limit or import
shared collection data, ask for the ``X-Re-DDNS-Admin-Token`` header:

    POST   /api/appstore/install, /dev-install, /uninstall
    *      /api/collections/_...        (except GET /_peers, which peers probe)
    DELETE /api/collections/<collection>/by-app/<owner>/<item>

Without this an app could uninstall another app "with its data", install a
container that mounts the whole collections tree read-write, or delete
other apps' contributions, which would make "write mine" a convention only.

The token is ``RE_DDNS_ADMIN_TOKEN`` when that is set.  Otherwise re-ddns
creates a random one the first time it starts and keeps it in
``<data>/admin_token`` (mode 0600, in the registry-data volume, so it
survives restarts).  The App Store reads that file through the Docker socket
it already holds (``GET /containers/re-ddns/archive``), so nothing needs
configuring, and only holders of the Docker socket, who control every
container anyway, can read it.  From a shell on the host::

    TOKEN=$(docker exec re-ddns cat /app/data/admin_token)
    curl -H "X-Re-DDNS-Admin-Token: $TOKEN" -X POST http://home.reflex-ddns.com/api/collections/_gc
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

logger = logging.getLogger("re-ddns.admin")

ADMIN_HEADER = "X-Re-DDNS-Admin-Token"
ENV_TOKEN = "RE_DDNS_ADMIN_TOKEN"

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
TOKEN_FILE = _DATA_DIR / "admin_token"

_cache: dict[str, str] = {}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _read_or_create(path: Path) -> str:
    token = _read(path)
    if token:
        return token
    path.parent.mkdir(parents=True, exist_ok=True)
    # No extension: the dev-mode reloader watching the data folder ignores such files.
    part = path.with_name(f"{path.name}_{secrets.token_hex(4)}")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secrets.token_hex(32) + "\n")
    try:
        # A link fails when another process created the file first: keep its token.
        os.link(part, path)
    except OSError:
        if not _read(path):         # empty leftover, or no hard links on this file system
            os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    token = _read(path)
    if not token:
        raise OSError(f"cannot keep the admin token in {path}")
    logger.info("admin token created in %s", path)
    return token


def admin_token(path: Path | None = None) -> str:
    """The token admin requests must carry; created on first use (see the module docstring)."""
    env = os.environ.get(ENV_TOKEN, "").strip()
    if env:
        return env
    target = path or TOKEN_FILE
    key = str(target)
    if key not in _cache:
        _cache[key] = _read_or_create(target)
    return _cache[key]


def require_admin(request: Request) -> None:
    """FastAPI dependency for the endpoints that change the platform."""
    try:
        expected = admin_token()
    except OSError as exc:
        logger.error("admin token unavailable: %s", exc)
        raise HTTPException(503, "the admin token of this re-ddns is unavailable") from exc
    given = request.headers.get(ADMIN_HEADER, "")
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, f"admin endpoint: send this re-ddns's admin token in {ADMIN_HEADER}")
