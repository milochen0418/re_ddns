"""DDNS Intent registry: which installed app provides which intent action.

Apps built on ``reflex_ddns_auth`` serve their intent manifest at
``/_ddns_intent/manifest`` on their backend.  This router reads it from every
registered service (straight over the Docker network, not through nginx) and
answers callers that start an intent without naming the app::

    GET /api/intent/providers?action=call.join
      -> {"action": "call.join", "providers": [{"app": "livekit", "title": "Audio Call"}]}

    GET /api/intent/catalog
      -> {"apps": {"livekit": {"call.join": {"title": ..., "route": ..., "params": ...}}}}

Manifests are cached per service for ``_CACHE_SECONDS``; a service that
re-registers (new ``registered_at``) is read again right away.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter

from re_ddns.api import registry_api

router = APIRouter(prefix="/api/intent", tags=["intent"])

MANIFEST_PATH = "/_ddns_intent/manifest"
_CACHE_SECONDS = 30
_TIMEOUT_SECONDS = 2

# subdomain -> (fetched_at, registered_at, actions)
_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}


async def _actions_of(client: httpx.AsyncClient, service: dict[str, Any]) -> dict[str, Any]:
    subdomain = service["subdomain"]
    registered_at = service.get("registered_at", "")
    now = time.monotonic()
    cached = _cache.get(subdomain)
    if cached and cached[1] == registered_at and now - cached[0] < _CACHE_SECONDS:
        return cached[2]

    url = f"http://{service['upstream_host']}:{service.get('backend_port', 8000)}{MANIFEST_PATH}"
    try:
        resp = await client.get(url)
        actions = resp.json().get("actions", {}) if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError, AttributeError):
        actions = {}
    if not isinstance(actions, dict):
        actions = {}
    _cache[subdomain] = (now, registered_at, actions)
    return actions


async def _catalog() -> dict[str, dict[str, Any]]:
    services = [s for s in registry_api.list_services() if s.get("upstream_host")]
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        results = await asyncio.gather(*(_actions_of(client, s) for s in services))
    return {s["subdomain"]: actions for s, actions in zip(services, results) if actions}


@router.get("/catalog")
async def intent_catalog():
    return {"apps": await _catalog()}


@router.get("/providers")
async def intent_providers(action: str):
    catalog = await _catalog()
    providers = [
        {"app": app, "title": actions[action].get("title", action)}
        for app, actions in sorted(catalog.items())
        if isinstance(actions.get(action), dict)
    ]
    return {"action": action, "providers": providers}
