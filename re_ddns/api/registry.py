"""Service registry backed by a JSON file.

This is the **single source of truth** for all registered services.
The API writes here; nginx and BIND9 configs are derived from it.

File layout (default ``/app/data/registry.json``)::

    {
      "services": {
        "testapp": {
          "subdomain": "testapp",
          "zone": "reflex-ddns.com",
          "upstream_host": "test-app",
          "frontend_port": 3000,
          "backend_port": 8000,
          "ip_address": "127.0.0.1",
          "ttl": 60,
          "registered_at": "2026-03-05T12:00:00"
        }
      }
    }

Thread-safe: all reads/writes are protected by a ``threading.Lock``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("/app/data/registry.json")
_lock = Lock()

# Module-level path — can be overridden via ``init()``.
_registry_path: Path = _DEFAULT_PATH


# ---------------------------------------------------------------------------
# Data shape helpers
# ---------------------------------------------------------------------------

def _empty_registry() -> dict[str, Any]:
    return {"services": {}}


def _ensure_file(path: Path) -> None:
    """Create the registry file (+ parent dirs) if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(_empty_registry(), indent=2) + "\n")
        logger.info("Created new registry file: %s", path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init(path: Path | str | None = None) -> Path:
    """Initialise the registry.  Call once at startup.

    Returns the resolved path for logging purposes.
    """
    global _registry_path
    if path is not None:
        _registry_path = Path(path)
    _ensure_file(_registry_path)
    logger.info("Registry initialised: %s", _registry_path)
    return _registry_path


def load() -> dict[str, Any]:
    """Return the full registry dict (deep copy)."""
    with _lock:
        _ensure_file(_registry_path)
        return json.loads(_registry_path.read_text())


def save(data: dict[str, Any]) -> None:
    """Overwrite the registry file atomically."""
    with _lock:
        _ensure_file(_registry_path)
        tmp = _registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(_registry_path)


def get_service(subdomain: str) -> dict[str, Any] | None:
    """Return a single service entry, or *None*."""
    data = load()
    return data["services"].get(subdomain)


def put_service(
    subdomain: str,
    zone: str,
    upstream_host: str,
    frontend_port: int = 3000,
    backend_port: int = 8000,
    ip_address: str = "127.0.0.1",
    ttl: int = 60,
) -> dict[str, Any]:
    """Insert or update a service.  Returns the entry written."""
    entry = {
        "subdomain": subdomain,
        "zone": zone,
        "upstream_host": upstream_host,
        "frontend_port": frontend_port,
        "backend_port": backend_port,
        "ip_address": ip_address,
        "ttl": ttl,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    data = load()
    data["services"][subdomain] = entry
    save(data)
    logger.info("Registry: put service '%s'", subdomain)
    return entry


def delete_service(subdomain: str) -> bool:
    """Remove a service.  Returns *True* if it existed."""
    data = load()
    if subdomain not in data["services"]:
        return False
    del data["services"][subdomain]
    save(data)
    logger.info("Registry: deleted service '%s'", subdomain)
    return True


def list_services() -> list[dict[str, Any]]:
    """Return a list of all service entries."""
    data = load()
    return list(data["services"].values())
