"""Re-DDNS App Store.

A Reflex app served at ``https://aapps.reflex-ddns.com`` that lists every
app declared in the catalog (``data/appstore_catalog.json`` — the
``smart_launch.sh`` parameter table) and lets you:

  • see each app's status (running / stopped / not installed)
  • Open a running app in a new tab
  • Start / Stop an installed app's container (via the Docker socket)
  • Install / Uninstall — v1 shows the exact ``smart_launch.sh`` command
    to run on the host (Mac), since building a new container requires a
    host-side ``docker compose`` build.

Status & control are done through the Docker Engine API over the Unix
socket bind-mounted at ``/var/run/docker.sock``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import reflex as rx

CATALOG_PATH = os.environ.get("CATALOG_PATH", "/app/data/appstore_catalog.json")
SERVICE_ZONE = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")


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

    # Command panel (Install / Uninstall instructions)
    show_command: bool = False
    command_title: str = ""
    command_text: str = ""
    command_hint: str = ""

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
    def show_install(self, subdomain: str):
        app = self._lookup(subdomain)
        if not app:
            return
        self.command_title = f"Install {app.get('name', subdomain)}"
        self.command_text = _build_install_cmd(app)
        self.command_hint = (
            "在主機 (Mac) 的 re_ddns 專案根目錄執行此指令來安裝並啟動這個 app。"
        )
        self.show_command = True

    @rx.event
    def show_uninstall(self, subdomain: str):
        app = self._lookup(subdomain)
        if not app:
            return
        self.command_title = f"Uninstall {app.get('name', subdomain)}"
        self.command_text = f"./smart_launch.sh --remove={subdomain}"
        self.command_hint = (
            "在主機 (Mac) 的 re_ddns 專案根目錄執行此指令來停止並移除這個 app"
            "（容器 + DNS + nginx 記錄）。"
        )
        self.show_command = True

    @rx.event
    def close_command(self):
        self.show_command = False


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
                    lambda: AppStoreState.show_uninstall(app["subdomain"]),
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
                    lambda: AppStoreState.show_uninstall(app["subdomain"]),
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
                lambda: AppStoreState.show_install(app["subdomain"]),
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


def command_panel() -> rx.Component:
    return rx.cond(
        AppStoreState.show_command,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.h3(
                        AppStoreState.command_title,
                        class_name="text-lg font-bold text-gray-900",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-5 w-5"),
                        on_click=AppStoreState.close_command,
                        class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg",
                    ),
                    class_name="flex items-center justify-between mb-3",
                ),
                rx.el.p(
                    AppStoreState.command_hint,
                    class_name="text-sm text-gray-500 mb-3",
                ),
                rx.el.code(
                    AppStoreState.command_text,
                    class_name="block w-full p-4 bg-gray-950 text-green-300 rounded-xl text-sm font-mono overflow-x-auto",
                ),
                class_name="w-full max-w-2xl bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6",
            on_click=AppStoreState.close_command,
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
        command_panel(),
        rx.el.div(
            # Header
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("layout-grid", class_name="h-8 w-8 text-blue-600"),
                        rx.el.h1(
                            "Re-DDNS App Store",
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
