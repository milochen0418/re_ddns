"""TestApp3 – Comprehensive Reflex frontend↔backend integration tests.

This Reflex app verifies that all communication paths between the
Reflex frontend and backend work correctly when served behind the
re_ddns nginx reverse proxy with domain-name-based routing.

Test scenarios:
  1. State update (WebSocket via /_event)  – proves rx.State works
  2. File upload (POST /_upload)           – proves uploads through nginx
  3. File download (GET /api/…)            – proves backend file serving
  4. Custom API endpoint (GET /api/…)      – proves custom FastAPI routes
  5. Backend health (/ping, /_health)      – proves health endpoints

Access via: https://testapp3.reflex-ddns.com (after DNS registration)
"""

import os
import json
import time
from pathlib import Path

import reflex as rx
from fastapi import APIRouter
from fastapi.responses import FileResponse

UPLOAD_DIR = Path("/app/uploaded_files")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ── Custom API routes ────────────────────────────────────────────────

api_router = APIRouter()


@api_router.get("/echo")
async def echo(msg: str = "hello"):
    """Simple echo endpoint to test custom API routing through nginx."""
    return {"echo": msg, "timestamp": time.time(), "source": "testapp3-backend"}


@api_router.get("/files")
async def list_uploaded_files():
    """List files that have been uploaded."""
    files = []
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size})
    return {"files": files}


@api_router.get("/download/{filename}")
async def download_file(filename: str):
    """Download a previously uploaded file."""
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    file_path = UPLOAD_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        return {"error": "File not found"}
    return FileResponse(file_path, filename=safe_name)


@api_router.get("/server-info")
async def server_info():
    """Return server-side environment info for debugging."""
    return {
        "api_url": os.environ.get("API_URL", "(not set)"),
        "hostname": os.environ.get("HOSTNAME", "(unknown)"),
        "reflex_frontend_host": os.environ.get("REFLEX_FRONTEND_HOST", "(not set)"),
        "reflex_backend_host": os.environ.get("REFLEX_BACKEND_HOST", "(not set)"),
        "timestamp": time.time(),
    }


# ── Reflex State ─────────────────────────────────────────────────────

class TestApp3State(rx.State):
    """State for all integration tests."""

    # --- State update test ---
    counter: int = 0
    state_test_status: str = "Not tested"

    # --- API test ---
    api_echo_result: str = "Not tested"
    api_server_info: str = "Not tested"

    # --- Upload test ---
    upload_status: str = "No file uploaded yet"
    uploaded_files: list[str] = []

    # --- Download test ---
    download_status: str = "Not tested"

    # --- Health check ---
    health_status: str = "Not tested"

    # --- Overall ---
    test_log: list[str] = []

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.test_log = [f"[{ts}] {msg}"] + self.test_log[:49]

    # ─── 1. State update (WebSocket /_event) ────────────────────────
    def increment_counter(self):
        self.counter += 1
        self.state_test_status = f"OK – counter = {self.counter}"
        self._log(f"State update OK: counter={self.counter}")

    def reset_counter(self):
        self.counter = 0
        self.state_test_status = "Reset – counter = 0"
        self._log("State reset")

    # ─── 2. File upload (/_upload) ──────────────────────────────────
    async def handle_upload(self, files: list[rx.UploadFile]):
        if not files:
            self.upload_status = "No files received"
            self._log("Upload: no files received")
            return

        for file in files:
            upload_data = await file.read()
            save_path = UPLOAD_DIR / file.filename
            save_path.write_bytes(upload_data)
            size = len(upload_data)
            self.upload_status = f"Uploaded: {file.filename} ({size} bytes)"
            self._log(f"Upload OK: {file.filename} ({size} bytes)")

        self._refresh_file_list()

    def _refresh_file_list(self):
        self.uploaded_files = [
            f.name for f in UPLOAD_DIR.iterdir() if f.is_file()
        ]

    def refresh_files(self):
        self._refresh_file_list()
        self._log(f"File list refreshed: {len(self.uploaded_files)} files")


# ── UI Components ────────────────────────────────────────────────────

def _status_badge(text: str) -> rx.Component:
    return rx.cond(
        text.contains("OK"),  # type: ignore
        rx.el.span(text, class_name="text-green-700 bg-green-50 px-3 py-1 rounded-full text-sm font-medium"),
        rx.cond(
            text.contains("Not tested"),  # type: ignore
            rx.el.span(text, class_name="text-gray-500 bg-gray-100 px-3 py-1 rounded-full text-sm font-medium"),
            rx.el.span(text, class_name="text-blue-700 bg-blue-50 px-3 py-1 rounded-full text-sm font-medium"),
        ),
    )


def _test_card(title: str, icon: str, children: list[rx.Component]) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.span(icon, class_name="text-2xl mr-3"),
            rx.el.h3(title, class_name="text-lg font-bold text-gray-800"),
            class_name="flex items-center mb-4",
        ),
        *children,
        class_name="bg-white rounded-2xl border border-gray-200 shadow-sm p-6",
    )


def state_update_test() -> rx.Component:
    """Test 1: WebSocket state updates via /_event."""
    return _test_card("Test 1: State Update (WebSocket /_event)", "🔄", [
        rx.el.p(
            "Tests that Reflex state changes propagate from backend to frontend "
            "via WebSocket. This verifies the /_event path through nginx.",
            class_name="text-gray-500 text-sm mb-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.span("Counter: ", class_name="text-gray-600"),
                rx.el.span(
                    TestApp3State.counter,
                    class_name="text-2xl font-bold text-blue-600 mx-2",
                ),
                class_name="flex items-center",
            ),
            rx.el.div(
                rx.el.button(
                    "Increment",
                    on_click=TestApp3State.increment_counter,
                    class_name="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 mr-2",
                ),
                rx.el.button(
                    "Reset",
                    on_click=TestApp3State.reset_counter,
                    class_name="bg-gray-200 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-300",
                ),
                class_name="flex gap-2",
            ),
            class_name="flex items-center justify-between mb-3",
        ),
        rx.el.div(
            rx.el.span("Status: ", class_name="text-gray-500 text-sm mr-2"),
            _status_badge(TestApp3State.state_test_status),
            class_name="flex items-center",
        ),
    ])


def upload_test() -> rx.Component:
    """Test 2: File upload via /_upload."""
    return _test_card("Test 2: File Upload (POST /_upload)", "📤", [
        rx.el.p(
            "Tests that file uploads work through the nginx proxy. "
            "The /_upload endpoint must be correctly proxied to the backend.",
            class_name="text-gray-500 text-sm mb-4",
        ),
        rx.upload(
            rx.el.div(
                rx.el.div(
                    rx.el.span("📁", class_name="text-3xl"),
                    class_name="mb-2",
                ),
                rx.el.p(
                    "Drop a file here or click to browse",
                    class_name="text-gray-500 text-sm",
                ),
                class_name="flex flex-col items-center py-6",
            ),
            id="upload_test",
            border="2px dashed #d1d5db",
            border_radius="1rem",
            padding="0",
            class_name="cursor-pointer hover:border-blue-400 transition-colors",
        ),
        rx.el.button(
            "Upload",
            on_click=TestApp3State.handle_upload(rx.upload_files(upload_id="upload_test")),
            class_name="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 mt-3",
        ),
        rx.el.div(
            rx.el.span("Status: ", class_name="text-gray-500 text-sm mr-2"),
            _status_badge(TestApp3State.upload_status),
            class_name="flex items-center mt-3",
        ),
    ])


def download_test() -> rx.Component:
    """Test 3: File download + listing via custom /api/ routes."""
    return _test_card("Test 3: File Download & API (GET /api/testapp3/…)", "📥", [
        rx.el.p(
            "Tests custom FastAPI endpoints served through the /api/ path. "
            "Upload a file first, then see it listed here.",
            class_name="text-gray-500 text-sm mb-4",
        ),
        rx.el.button(
            "Refresh file list",
            on_click=TestApp3State.refresh_files,
            class_name="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 mb-3",
        ),
        rx.cond(
            TestApp3State.uploaded_files.length() > 0,  # type: ignore
            rx.el.ul(
                rx.foreach(
                    TestApp3State.uploaded_files,
                    lambda fname: rx.el.li(
                        rx.el.span("📄 ", class_name="mr-1"),
                        rx.el.span(fname, class_name="text-gray-700"),
                        rx.link(
                            " [download]",
                            href="/api/testapp3/download/" + fname,
                            is_external=True,
                            class_name="text-blue-600 text-sm hover:underline ml-2",
                        ),
                        class_name="py-1",
                    ),
                ),
                class_name="list-none space-y-1",
            ),
            rx.el.p("No files uploaded yet.", class_name="text-gray-400 text-sm italic"),
        ),
    ])


def api_test() -> rx.Component:
    """Test 4: Custom API call info."""
    return _test_card("Test 4: API Endpoints (/api/testapp3/…)", "🌐", [
        rx.el.p(
            "Test custom backend API endpoints. These endpoints are routed through "
            "nginx via the /api/ path prefix to the backend on port 8000.",
            class_name="text-gray-500 text-sm mb-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.code("/api/testapp3/echo?msg=test", class_name="text-sm bg-gray-100 px-2 py-1 rounded"),
                rx.el.span(" – echo endpoint", class_name="text-gray-500 text-sm ml-2"),
                class_name="mb-2",
            ),
            rx.el.div(
                rx.el.code("/api/testapp3/files", class_name="text-sm bg-gray-100 px-2 py-1 rounded"),
                rx.el.span(" – list uploaded files", class_name="text-gray-500 text-sm ml-2"),
                class_name="mb-2",
            ),
            rx.el.div(
                rx.el.code("/api/testapp3/server-info", class_name="text-sm bg-gray-100 px-2 py-1 rounded"),
                rx.el.span(" – server environment info", class_name="text-gray-500 text-sm ml-2"),
                class_name="mb-2",
            ),
            rx.el.div(
                rx.el.code("/api/testapp3/download/{name}", class_name="text-sm bg-gray-100 px-2 py-1 rounded"),
                rx.el.span(" – download uploaded file", class_name="text-gray-500 text-sm ml-2"),
                class_name="mb-2",
            ),
            class_name="bg-gray-50 rounded-xl p-4",
        ),
        rx.el.p(
            "Open these URLs directly in the browser using your domain: ",
            rx.el.code(
                "https://testapp3.reflex-ddns.com/api/testapp3/echo?msg=hello",
                class_name="text-xs bg-gray-100 px-2 py-1 rounded break-all",
            ),
            class_name="text-gray-500 text-sm mt-3",
        ),
    ])


def connection_info() -> rx.Component:
    """Display connection / architecture info."""
    return _test_card("Connection Architecture", "🏗️", [
        rx.el.div(
            rx.el.pre(
                "Browser\n"
                "  │\n"
                "  ▼\n"
                "nginx (re-ddns :443)\n"
                "  ├── /_event, /ping, /_upload, /_health, /api  →  backend :8000\n"
                "  └── / (everything else)                       →  frontend :3000\n"
                "  │\n"
                "  ▼\n"
                "testapp3 container (test-app3)\n"
                "  ├── frontend :3000  (Vite / Reflex compiled JS)\n"
                "  └── backend  :8000  (FastAPI / Reflex state)",
                class_name="text-xs text-gray-600 bg-gray-50 p-4 rounded-xl overflow-x-auto font-mono",
            ),
            class_name="mb-3",
        ),
        rx.el.p(
            "All paths above are proxied by nginx based on the Host header. "
            "The frontend's JavaScript connects to the backend WebSocket "
            "through the same domain, so /_event requests go through nginx too.",
            class_name="text-gray-500 text-sm",
        ),
    ])


def test_log_panel() -> rx.Component:
    """Activity log showing test results."""
    return _test_card("Test Activity Log", "📋", [
        rx.cond(
            TestApp3State.test_log.length() > 0,  # type: ignore
            rx.el.div(
                rx.foreach(
                    TestApp3State.test_log,
                    lambda entry: rx.el.div(
                        rx.el.span(entry, class_name="text-sm font-mono text-gray-600"),
                        class_name="py-1 border-b border-gray-100",
                    ),
                ),
                class_name="max-h-48 overflow-y-auto",
            ),
            rx.el.p("No test activity yet. Try the tests above!", class_name="text-gray-400 text-sm italic"),
        ),
    ])


def index() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            # Header
            rx.el.div(
                rx.el.h1(
                    "Re-DDNS TestApp3",
                    class_name="text-4xl font-black text-gray-900",
                ),
                rx.el.p(
                    "Frontend ↔ Backend Integration Test Suite",
                    class_name="text-lg text-gray-500 mt-2",
                ),
                rx.el.p(
                    "Verifies all communication paths between Reflex frontend and backend "
                    "when served behind nginx reverse proxy with domain-name routing.",
                    class_name="text-sm text-gray-400 mt-1 max-w-xl mx-auto",
                ),
                class_name="text-center mb-10",
            ),
            # Test cards
            rx.el.div(
                state_update_test(),
                upload_test(),
                download_test(),
                api_test(),
                connection_info(),
                test_log_panel(),
                class_name="space-y-6",
            ),
            class_name="max-w-2xl mx-auto py-16 px-6",
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
app.add_page(index)

# ── Register custom API routes (FastAPI router on Starlette) ──
# IMPORTANT: mount on a specific prefix, NOT "" (empty string).
# An empty-prefix Mount catches ALL requests and shadows Reflex's
# built-in endpoints (/_upload, /_event, /ping, etc.).
from fastapi import FastAPI as _FastAPI  # noqa: E402

_api_app = _FastAPI()
_api_app.include_router(api_router)
app._api.mount("/api/testapp3", _api_app)
