"""Agentic App Store.

A Reflex app served at ``https://aapps.reflex-ddns.com`` that lists every
app declared in the catalog (``data/appstore_catalog.json`` — the
``smart_launch.sh`` parameter table) and lets you:

  • see each app's status (running / stopped / not installed)
  • Open a running app in a new tab
  • Start / Stop an installed app's container (via the Docker socket)
  • Install — done **in-page** with a live progress bar. The App Store
    asks re-ddns (which owns the Docker socket and the install/progress
    manager) to create + start the app's container and then polls
    ``/api/appstore/status/<sub>`` to render progress.
  • Uninstall — calls re-ddns ``DELETE /api/service/<sub>`` which stops the
    container and removes the DNS + nginx records.

Status & control are done through the Docker Engine API over the Unix
socket bind-mounted at ``/var/run/docker.sock``; installs are orchestrated
by re-ddns over its own copy of that socket.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import reflex as rx

CATALOG_PATH = os.environ.get("CATALOG_PATH", "/app/data/appstore_catalog.json")
SERVICE_ZONE = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
# re-ddns hosts the install orchestrator + progress manager.
RE_DDNS_API_URL = os.environ.get("RE_DDNS_API_URL", "http://re-ddns:8000")


# ---------------------------------------------------------------------------
# Catalog + Docker helpers (plain Python, called from state event handlers)
# ---------------------------------------------------------------------------

def _load_catalog() -> list[dict]:
    """Read the app catalog JSON. Returns [] on any error."""
    try:
        data = json.loads(Path(CATALOG_PATH).read_text())
        return data.get("apps", [])
    except Exception as exc:  # noqa: BLE001
        print(f"[appstore] WARNING: cannot read catalog {CATALOG_PATH}: {exc}")
        return []


def _container_name(app: dict) -> str:
    """smart_launch.sh names every launched container smart-app-<subdomain>."""
    return f"smart-app-{app['subdomain']}"


def _docker_request(method: str, path: str):
    """Call the Docker Engine API over the Unix socket. Returns the response
    object, or ``None`` if the socket is unavailable."""
    if not os.path.exists(DOCKER_SOCK):
        return None
    try:
        transport = httpx.HTTPTransport(uds=DOCKER_SOCK)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=20.0) as client:
            return client.request(method, path)
    except Exception as exc:  # noqa: BLE001
        print(f"[appstore] docker {method} {path} failed: {exc}")
        return None


def _container_status(app: dict) -> str:
    """Return one of: running | stopped | not_installed | unknown."""
    r = _docker_request("GET", f"/containers/{_container_name(app)}/json")
    if r is None:
        return "unknown"
    if r.status_code == 404:
        return "not_installed"
    if r.status_code == 200:
        try:
            running = r.json().get("State", {}).get("Running", False)
        except Exception:  # noqa: BLE001
            running = False
        return "running" if running else "stopped"
    return "unknown"


def _build_install_cmd(app: dict) -> str:
    """Reconstruct the smart_launch.sh command from a catalog entry."""
    parts = ["./smart_launch.sh"]
    branch = app.get("branch") or ""
    if branch and branch != "main":
        parts.append(f"--branch={branch}")
    if app.get("commit"):
        parts.append(f"--commit={app['commit']}")
    if app.get("subdir"):
        parts.append(f"--subdir={app['subdir']}")
    for vol in app.get("volumes", []) or []:
        parts.append(f"-v {vol}")
    parts.append(app["github_repo"])
    parts.append(app["app_name"])
    parts.append(app["subdomain"])
    if app.get("env_file"):
        parts.append(app["env_file"])
    return " ".join(parts)


_STATUS_LABEL = {
    "running": "Running",
    "stopped": "Stopped",
    "not_installed": "Not installed",
    "unknown": "Unknown",
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AppStoreState(rx.State):
    """Holds the merged catalog + live status and drives all actions."""

    apps: list[dict[str, str]] = []
    loading: bool = False
    message: str = ""
    message_kind: str = "info"  # info | success | error

    # Live install progress (driven by re-ddns /api/appstore/status).
    show_progress: bool = False
    active_sub: str = ""
    active_name: str = ""
    install_status: str = ""    # installing | installed | error
    install_phase: str = ""
    install_percent: int = 0
    install_message: str = ""
    install_log: list[str] = []

    # Dynamic env-var config form (for apps that declare "env_schema").
    show_env_form: bool = False
    env_form_sub: str = ""
    env_form_name: str = ""
    env_form_error: str = ""
    env_form_schema: list[dict[str, str]] = []

    @rx.var
    def progress_width(self) -> str:
        pct = max(0, min(100, self.install_percent))
        return f"{pct}%"

    @rx.var
    def install_busy(self) -> bool:
        return self.install_status == "installing"

    def _lookup(self, subdomain: str) -> dict | None:
        for app in _load_catalog():
            if app["subdomain"] == subdomain:
                return app
        return None

    @rx.event
    def refresh(self):
        """Reload catalog and recompute each app's live status."""
        self.loading = True
        self.message = ""
        yield
        rows: list[dict[str, str]] = []
        for app in _load_catalog():
            status = _container_status(app)
            rows.append(
                {
                    "id": str(app.get("id", app["subdomain"])),
                    "name": str(app.get("name", app["subdomain"])),
                    "description": str(app.get("description", "")),
                    "icon": str(app.get("icon", "box")),
                    "subdomain": str(app["subdomain"]),
                    "url": f"https://{app['subdomain']}.{SERVICE_ZONE}",
                    "status": status,
                    "status_label": _STATUS_LABEL.get(status, "Unknown"),
                    "install_cmd": _build_install_cmd(app),
                    "uninstall_cmd": f"./smart_launch.sh --remove={app['subdomain']}",
                }
            )
        self.apps = rows
        self.loading = False

    @rx.event
    def start_app(self, subdomain: str):
        app = self._lookup(subdomain)
        if not app:
            return
        name = _container_name(app)
        r = _docker_request("POST", f"/containers/{name}/start")
        if r is None:
            self.message = "Docker socket unavailable — cannot start container."
            self.message_kind = "error"
        elif r.status_code in (204, 304):
            self.message = f"Started {name}."
            self.message_kind = "success"
        elif r.status_code == 404:
            self.message = f"{name} is not installed yet. Use Install first."
            self.message_kind = "error"
        else:
            self.message = f"Start failed (HTTP {r.status_code})."
            self.message_kind = "error"
        yield AppStoreState.refresh

    @rx.event
    def stop_app(self, subdomain: str):
        app = self._lookup(subdomain)
        if not app:
            return
        name = _container_name(app)
        r = _docker_request("POST", f"/containers/{name}/stop")
        if r is None:
            self.message = "Docker socket unavailable — cannot stop container."
            self.message_kind = "error"
        elif r.status_code in (204, 304):
            self.message = f"Stopped {name}."
            self.message_kind = "success"
        else:
            self.message = f"Stop failed (HTTP {r.status_code})."
            self.message_kind = "error"
        yield AppStoreState.refresh

    @rx.event
    def begin_install(self, subdomain: str):
        """Entry point for the Install button.

        If the app declares an ``env_schema`` in the catalog, open a settings
        form to collect those values first; otherwise install right away.
        """
        app = self._lookup(subdomain)
        if not app:
            return
        schema = app.get("env_schema") or []
        if schema:
            self.env_form_sub = subdomain
            self.env_form_name = str(app.get("name", subdomain))
            self.env_form_error = ""
            self.env_form_schema = [
                {
                    "key": str(item.get("key", "")),
                    "label": str(item.get("label", item.get("key", ""))),
                    "placeholder": str(item.get("placeholder", "")),
                    "help": str(item.get("help", "")),
                    "secret": "1" if item.get("secret") else "",
                    "required": "1" if item.get("required", True) else "",
                }
                for item in schema
                if item.get("key")
            ]
            self.show_env_form = True
            return
        return AppStoreState.install_app(subdomain, {})

    @rx.event
    def cancel_env_form(self):
        self.show_env_form = False
        self.env_form_sub = ""
        self.env_form_schema = []
        self.env_form_error = ""

    @rx.event
    def submit_env_form(self, form_data: dict):
        """Validate the required settings, then kick off the install."""
        sub = self.env_form_sub
        missing = [
            item["label"] or item["key"]
            for item in self.env_form_schema
            if item.get("required") == "1"
            and not str(form_data.get(item["key"], "")).strip()
        ]
        if missing:
            self.env_form_error = "請填寫必填欄位：" + "、".join(missing)
            return
        env = {
            k: str(v)
            for k, v in form_data.items()
            if str(v).strip() != ""
        }
        self.show_env_form = False
        self.env_form_error = ""
        return AppStoreState.install_app(sub, env)

    @rx.event
    def install_app(self, subdomain: str, env: dict[str, str] | None = None):
        """Ask re-ddns to install the app, then poll progress in-page."""
        app = self._lookup(subdomain)
        if not app:
            return
        display = app.get("name", subdomain)
        # Reset progress UI.
        self.show_progress = True
        self.active_sub = subdomain
        self.active_name = display
        self.install_status = "installing"
        self.install_phase = "queued"
        self.install_percent = 2
        self.install_message = "正在送出安裝請求…"
        self.install_log = []
        self.message = ""

        spec = {
            "subdomain": subdomain,
            "github_repo": app["github_repo"],
            "app_name": app["app_name"],
            "name": display,
            "branch": app.get("branch") or "main",
            "commit": app.get("commit") or "",
            "subdir": app.get("subdir") or "",
            "zone": SERVICE_ZONE,
            "volumes": app.get("volumes") or [],
            "env_file": app.get("env_file") or "",
            "env": env or {},
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(f"{RE_DDNS_API_URL}/api/appstore/install", json=spec)
            if r.status_code != 200:
                self.install_status = "error"
                self.install_message = f"無法開始安裝 (HTTP {r.status_code})：{r.text[:200]}"
                return
        except Exception as exc:  # noqa: BLE001
            self.install_status = "error"
            self.install_message = f"無法連線 re-ddns：{exc}"
            return
        # Kick off background polling.
        return AppStoreState.poll_progress

    @rx.event(background=True)
    async def poll_progress(self):
        """Poll re-ddns for install progress until it finishes or fails."""
        async with self:
            sub = self.active_sub
        if not sub:
            return
        while True:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        f"{RE_DDNS_API_URL}/api/appstore/status/{sub}"
                    )
                data = r.json() if r.status_code == 200 else {}
            except Exception:  # noqa: BLE001
                data = {}

            async with self:
                if self.active_sub != sub or not self.show_progress:
                    return  # user moved on / closed
                if data:
                    self.install_status = data.get("status", self.install_status)
                    self.install_phase = data.get("phase", self.install_phase)
                    self.install_percent = int(data.get("percent", self.install_percent))
                    self.install_message = data.get("message", self.install_message)
                    log = data.get("log", [])
                    if isinstance(log, list):
                        self.install_log = [str(x) for x in log[-14:]]
                status = self.install_status

            if status in ("installed", "error"):
                if status == "installed":
                    async with self:
                        self.message = f"{self.active_name} 安裝完成！"
                        self.message_kind = "success"
                # Refresh the catalog status grid.
                yield AppStoreState.refresh
                return

            await asyncio.sleep(1.5)

    @rx.event
    def uninstall_app(self, subdomain: str):
        """Stop the container and remove DNS + nginx records via re-ddns."""
        app = self._lookup(subdomain)
        name = app.get("name", subdomain) if app else subdomain
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.delete(f"{RE_DDNS_API_URL}/api/service/{subdomain}")
            if r.status_code == 200 and r.json().get("success"):
                self.message = f"{name} 已移除（容器 + DNS + nginx）。"
                self.message_kind = "success"
            else:
                self.message = f"{name} 移除完成（部分項目可能原本就不存在）。"
                self.message_kind = "info"
        except Exception as exc:  # noqa: BLE001
            self.message = f"移除失敗：{exc}"
            self.message_kind = "error"
        yield AppStoreState.refresh

    @rx.event
    def close_progress(self):
        self.show_progress = False
        self.active_sub = ""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def status_badge(app: rx.Var[dict]) -> rx.Component:
    return rx.el.span(
        rx.el.span(
            class_name=rx.match(
                app["status"],
                ("running", "h-2 w-2 rounded-full bg-green-500"),
                ("stopped", "h-2 w-2 rounded-full bg-yellow-500"),
                ("not_installed", "h-2 w-2 rounded-full bg-gray-300"),
                "h-2 w-2 rounded-full bg-gray-300",
            ),
        ),
        rx.el.span(app["status_label"], class_name="text-xs font-bold"),
        class_name=rx.match(
            app["status"],
            (
                "running",
                "flex items-center gap-2 px-3 py-1 rounded-full bg-green-50 text-green-700",
            ),
            (
                "stopped",
                "flex items-center gap-2 px-3 py-1 rounded-full bg-yellow-50 text-yellow-700",
            ),
            (
                "not_installed",
                "flex items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-500",
            ),
            "flex items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-500",
        ),
    )


def _btn(label: str, icon: str, on_click, color: str) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, class_name="h-4 w-4"),
        rx.el.span(label),
        on_click=on_click,
        class_name=f"flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold transition-all {color}",
    )


def open_button(app: rx.Var[dict]) -> rx.Component:
    return rx.link(
        rx.el.div(
            rx.icon("external-link", class_name="h-4 w-4"),
            rx.el.span("Open"),
            class_name="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold bg-blue-600 text-white hover:bg-blue-700 transition-all",
        ),
        href=app["url"],
        is_external=True,
    )


def action_buttons(app: rx.Var[dict]) -> rx.Component:
    return rx.match(
        app["status"],
        (
            "running",
            rx.el.div(
                open_button(app),
                _btn(
                    "Stop",
                    "square",
                    lambda: AppStoreState.stop_app(app["subdomain"]),
                    "bg-yellow-50 text-yellow-700 hover:bg-yellow-100",
                ),
                _btn(
                    "Uninstall",
                    "trash-2",
                    lambda: AppStoreState.uninstall_app(app["subdomain"]),
                    "bg-red-50 text-red-600 hover:bg-red-100",
                ),
                class_name="flex flex-wrap items-center gap-2",
            ),
        ),
        (
            "stopped",
            rx.el.div(
                _btn(
                    "Start",
                    "play",
                    lambda: AppStoreState.start_app(app["subdomain"]),
                    "bg-green-600 text-white hover:bg-green-700",
                ),
                _btn(
                    "Uninstall",
                    "trash-2",
                    lambda: AppStoreState.uninstall_app(app["subdomain"]),
                    "bg-red-50 text-red-600 hover:bg-red-100",
                ),
                class_name="flex flex-wrap items-center gap-2",
            ),
        ),
        # not_installed / unknown
        rx.el.div(
            _btn(
                "Install",
                "download",
                lambda: AppStoreState.begin_install(app["subdomain"]),
                "bg-gray-900 text-white hover:bg-black",
            ),
            class_name="flex flex-wrap items-center gap-2",
        ),
    )


def app_card(app: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.icon(app["icon"], class_name="h-6 w-6 text-blue-600"),
                class_name="p-3 bg-blue-100 rounded-2xl shrink-0",
            ),
            rx.el.div(
                rx.el.div(
                    rx.el.h3(app["name"], class_name="text-lg font-bold text-gray-900"),
                    status_badge(app),
                    class_name="flex items-center justify-between gap-3",
                ),
                rx.el.p(
                    app["description"],
                    class_name="text-sm text-gray-500 mt-1",
                ),
                rx.el.p(
                    app["url"],
                    class_name="text-xs text-gray-400 font-mono mt-2",
                ),
                class_name="flex-1 min-w-0",
            ),
            class_name="flex items-start gap-4",
        ),
        rx.el.div(
            action_buttons(app),
            class_name="mt-5",
        ),
        class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm",
    )


def env_field(item: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            item["label"],
            rx.cond(
                item["required"] == "1",
                rx.el.span(" *", class_name="text-red-500"),
                rx.fragment(),
            ),
            class_name="text-sm font-semibold text-gray-700",
        ),
        rx.el.input(
            name=item["key"],
            placeholder=item["placeholder"],
            type=rx.cond(item["secret"] == "1", "password", "text"),
            auto_complete="off",
            class_name="mt-1 w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
        ),
        rx.cond(
            item["help"] != "",
            rx.el.p(
                item["help"],
                class_name="text-xs text-gray-500 mt-1 whitespace-pre-line leading-relaxed",
            ),
            rx.fragment(),
        ),
        rx.el.p(item["key"], class_name="text-xs text-gray-400 font-mono mt-1"),
        class_name="flex flex-col",
    )


def env_form_panel() -> rx.Component:
    return rx.cond(
        AppStoreState.show_env_form,
        rx.el.div(
            rx.el.div(
                # Header
                rx.el.div(
                    rx.el.div(
                        rx.icon("settings", class_name="h-6 w-6 text-blue-600"),
                        rx.el.h3(
                            "設定 " + AppStoreState.env_form_name,
                            class_name="text-lg font-bold text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-5 w-5"),
                        on_click=AppStoreState.cancel_env_form,
                        class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg",
                    ),
                    class_name="flex items-center justify-between mb-2",
                ),
                rx.el.p(
                    "這個應用程式需要一些設定才能運作。這些值會在安裝時注入容器環境變數並寫入 .env。",
                    class_name="text-sm text-gray-500 mb-4",
                ),
                rx.cond(
                    AppStoreState.env_form_error != "",
                    rx.el.div(
                        AppStoreState.env_form_error,
                        class_name="p-3 mb-4 bg-red-50 text-red-700 rounded-xl text-sm border border-red-100",
                    ),
                    rx.fragment(),
                ),
                rx.form(
                    rx.el.div(
                        rx.foreach(AppStoreState.env_form_schema, env_field),
                        class_name="flex flex-col gap-4",
                    ),
                    rx.el.div(
                        rx.el.button(
                            "取消",
                            type="button",
                            on_click=AppStoreState.cancel_env_form,
                            class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200",
                        ),
                        rx.el.button(
                            rx.icon("download", class_name="h-4 w-4"),
                            rx.el.span("安裝"),
                            type="submit",
                            class_name="flex items-center gap-2 px-4 py-2 bg-gray-900 text-white font-semibold rounded-xl hover:bg-black",
                        ),
                        class_name="flex justify-end gap-2 mt-6",
                    ),
                    on_submit=AppStoreState.submit_env_form,
                    reset_on_submit=False,
                ),
                class_name="w-full max-w-lg bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6",
        ),
        None,
    )


def progress_panel() -> rx.Component:
    return rx.cond(
        AppStoreState.show_progress,        rx.el.div(
            rx.el.div(
                # Header
                rx.el.div(
                    rx.el.div(
                        rx.cond(
                            AppStoreState.install_status == "error",
                            rx.icon("circle-alert", class_name="h-6 w-6 text-red-600"),
                            rx.cond(
                                AppStoreState.install_status == "installed",
                                rx.icon("circle-check-big", class_name="h-6 w-6 text-green-600"),
                                rx.icon("loader-circle", class_name="h-6 w-6 text-blue-600 animate-spin"),
                            ),
                        ),
                        rx.el.h3(
                            "安裝 " + AppStoreState.active_name,
                            class_name="text-lg font-bold text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-5 w-5"),
                        on_click=AppStoreState.close_progress,
                        class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg",
                    ),
                    class_name="flex items-center justify-between mb-4",
                ),
                # Progress bar
                rx.el.div(
                    rx.el.div(
                        class_name=rx.cond(
                            AppStoreState.install_status == "error",
                            "h-full bg-red-500 transition-all duration-500",
                            "h-full bg-blue-600 transition-all duration-500",
                        ),
                        style={"width": AppStoreState.progress_width},
                    ),
                    class_name="w-full h-3 bg-gray-100 rounded-full overflow-hidden",
                ),
                rx.el.div(
                    rx.el.span(
                        AppStoreState.install_message,
                        class_name="text-sm font-medium text-gray-700",
                    ),
                    rx.el.span(
                        AppStoreState.install_percent.to_string() + "%",
                        class_name="text-sm font-bold text-gray-900",
                    ),
                    class_name="flex items-center justify-between mt-2 mb-4",
                ),
                # Log tail
                rx.el.div(
                    rx.foreach(
                        AppStoreState.install_log,
                        lambda line: rx.el.div(line, class_name="whitespace-pre-wrap"),
                    ),
                    class_name="w-full h-48 p-3 bg-gray-950 text-green-300 rounded-xl text-xs font-mono overflow-y-auto",
                ),
                # Footer button
                rx.el.div(
                    rx.cond(
                        AppStoreState.install_busy,
                        rx.el.button(
                            "安裝進行中…（可關閉視窗，安裝會在背景繼續）",
                            on_click=AppStoreState.close_progress,
                            class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200",
                        ),
                        rx.el.button(
                            "完成",
                            on_click=AppStoreState.close_progress,
                            class_name="px-4 py-2 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700",
                        ),
                    ),
                    class_name="flex justify-end mt-4",
                ),
                class_name="w-full max-w-2xl bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6",
        ),
        None,
    )


def message_banner() -> rx.Component:
    return rx.cond(
        AppStoreState.message != "",
        rx.el.div(
            rx.icon(
                rx.match(
                    AppStoreState.message_kind,
                    ("success", "check-circle-2"),
                    ("error", "alert-circle"),
                    "info",
                ),
                class_name="h-5 w-5 mr-2 shrink-0",
            ),
            rx.el.span(AppStoreState.message, class_name="font-medium"),
            class_name=rx.match(
                AppStoreState.message_kind,
                (
                    "success",
                    "flex items-center p-4 bg-green-50 text-green-800 rounded-xl border border-green-100 mb-6",
                ),
                (
                    "error",
                    "flex items-center p-4 bg-red-50 text-red-800 rounded-xl border border-red-100 mb-6",
                ),
                "flex items-center p-4 bg-blue-50 text-blue-800 rounded-xl border border-blue-100 mb-6",
            ),
        ),
        None,
    )


def index() -> rx.Component:
    return rx.el.main(
        progress_panel(),
        env_form_panel(),
        rx.el.div(
            # Header
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("layout-grid", class_name="h-8 w-8 text-blue-600"),
                        rx.el.h1(
                            "Agentic App Store",
                            class_name="text-3xl font-black text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.button(
                        rx.cond(
                            AppStoreState.loading,
                            rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                            rx.icon("refresh-cw", class_name="h-4 w-4"),
                        ),
                        rx.el.span("Refresh"),
                        on_click=AppStoreState.refresh,
                        disabled=AppStoreState.loading,
                        class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all disabled:opacity-50",
                    ),
                    class_name="flex items-center justify-between mb-2",
                ),
                rx.el.p(
                    "Browse, install, and manage Reflex apps deployed behind re-ddns.",
                    class_name="text-gray-500",
                ),
                class_name="mb-8",
            ),
            message_banner(),
            # Grid of apps
            rx.cond(
                AppStoreState.apps.length() > 0,
                rx.el.div(
                    rx.foreach(AppStoreState.apps, app_card),
                    class_name="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6",
                ),
                rx.el.div(
                    rx.icon("package-open", class_name="h-12 w-12 text-gray-300 mb-4"),
                    rx.el.p(
                        "No apps in the catalog yet.",
                        class_name="text-gray-400 font-medium",
                    ),
                    rx.el.p(
                        "Add entries to data/appstore_catalog.json.",
                        class_name="text-gray-400 text-sm mt-1",
                    ),
                    class_name="flex flex-col items-center justify-center h-64 border-2 border-dashed border-gray-100 rounded-3xl",
                ),
            ),
            class_name="max-w-6xl mx-auto py-12 px-6",
        ),
        class_name="min-h-screen bg-gray-50 font-['Inter']",
    )


app = rx.App(
    theme=rx.theme(appearance="light"),
    head_components=[
        rx.el.link(rel="preconnect", href="https://fonts.googleapis.com"),
        rx.el.link(
            rel="preconnect", href="https://fonts.gstatic.com", cross_origin=""
        ),
        rx.el.link(
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap",
            rel="stylesheet",
        ),
    ],
)
app.add_page(index, on_load=AppStoreState.refresh)
