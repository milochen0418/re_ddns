"""The admin token: created once, kept, and required by the endpoints that change the platform."""

import asyncio
import os
import stat

import httpx
from fastapi import Depends, FastAPI

from re_ddns.api import admin_auth, install_manager
from re_ddns.api.admin_auth import ADMIN_HEADER, admin_token, require_admin


def _get(app: FastAPI, method: str, path: str, headers: dict | None = None, json: dict | None = None) -> int:
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://re-ddns") as c:
            return (await c.request(method, path, headers=headers or {}, json=json)).status_code

    return asyncio.run(go())


def test_token_file_is_created_once_private_and_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("RE_DDNS_ADMIN_TOKEN", raising=False)
    admin_auth._cache.clear()
    path = tmp_path / "data" / "admin_token"
    first = admin_token(path)
    assert len(first) == 64 and path.read_text().strip() == first
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["admin_token"]       # no .part left behind
    admin_auth._cache.clear()
    assert admin_token(path) == first                                        # a restart keeps it
    path.write_text("")                                                      # an empty leftover is replaced
    admin_auth._cache.clear()
    again = admin_token(path)
    assert again and again != first and path.read_text().strip() == again


def test_env_token_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("RE_DDNS_ADMIN_TOKEN", "from-env")
    assert admin_token(tmp_path / "admin_token") == "from-env"
    assert not (tmp_path / "admin_token").exists()


def test_require_admin(admin_token):
    app = FastAPI()

    @app.post("/x", dependencies=[Depends(require_admin)])
    async def x():
        return {"ok": True}

    assert _get(app, "POST", "/x") == 401
    assert _get(app, "POST", "/x", {ADMIN_HEADER: "nope"}) == 401
    assert _get(app, "POST", "/x", {ADMIN_HEADER: admin_token}) == 200


def test_install_endpoints_need_the_admin_token(admin_token, monkeypatch, tmp_path):
    # No Docker here: with the token the handlers stop at the missing socket (503).
    monkeypatch.setattr(install_manager, "DOCKER_SOCKET", str(tmp_path / "no-docker.sock"))
    monkeypatch.setattr(install_manager, "_STORE_PATH", tmp_path / "install_jobs.json")
    app = FastAPI()
    app.include_router(install_manager.router)
    body = {"subdomain": "x", "github_repo": "https://example.invalid/x.git", "app_name": "x", "local_path": "/x"}
    for path in ("/api/appstore/install", "/api/appstore/dev-install", "/api/appstore/uninstall"):
        assert _get(app, "POST", path, json=body) == 401, path
        assert _get(app, "POST", path, {ADMIN_HEADER: admin_token}, json=body) == 503, path
    assert _get(app, "GET", "/api/appstore/status") == 200                     # reading progress stays open
