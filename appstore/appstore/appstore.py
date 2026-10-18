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
    ``/api/appstore/status/<sub>`` to render progress.  Several apps can be
    installed (or removed) at the same time: each job has its own poller,
    each card shows its own progress bar, and the progress panel switches
    between the jobs in flight.
  • Uninstall — after a confirmation, asks re-ddns (``POST
    /api/appstore/uninstall``) to stop and delete the container, then drop
    the registry entry, DNS record, nginx config and TLS certificate; the
    same progress panel as Install follows each step. Named Docker volumes
    (the app's data) are kept unless the user ticks the box.

Status & control are done through the Docker Engine API over the Unix
socket bind-mounted at ``/var/run/docker.sock``; installs are orchestrated
by re-ddns over its own copy of that socket.

The page is translated, and shares its language with ``/monitor`` (see
``lang.py``).  Every text comes from the ``i18n`` tables; one with
``{placeholders}`` is stored as a key plus its arguments and rendered by a
computed var, so it follows a language switch made on either page.  The app
descriptions and settings-form texts come from the catalog entry's optional
``i18n`` block (see ``_localized``), falling back to its base fields.
"""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
from collections.abc import Mapping
from pathlib import Path

import httpx
import reflex as rx

from . import i18n
from .lang import LocaleState, language_picker
from .monitor import MonitorState, monitor

CATALOG_PATH = os.environ.get("CATALOG_PATH", "/app/data/appstore_catalog.json")
SERVICE_ZONE = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
# re-ddns hosts the install orchestrator + progress manager.
RE_DDNS_API_URL = os.environ.get("RE_DDNS_API_URL", "http://re-ddns:8000")
# Dev mode: show the "Dev" button on app cards (off by default).
DEV_MODE_ENABLED = os.environ.get("APPSTORE_DEV_MODE", "0") == "1"
# Dev mode path autocomplete: the Docker host's home folder is bind-mounted
# read-only at HOST_FS_PREFIX + <host path>, so the Dev form can list the
# host's folders (the path the user types is a *host* path).
HOST_HOME = os.environ.get("HOST_HOME", "").rstrip("/")
HOST_FS_PREFIX = os.environ.get("HOST_FS_PREFIX", "/hostfs").rstrip("/")
DEV_SUGGEST_LIMIT = 50
# A job's status while it is still going.
_BUSY = ("installing", "uninstalling")

# Keys the Dev path input handles itself: stop Tab from moving focus, the
# arrows from moving the caret, and Enter from submitting while a suggestion
# is highlighted. Capture phase, so React's onKeyDown still sees the key.
_DEV_PATH_KEYS_JS = """
if (!window.__devPathKeys) {
  window.__devPathKeys = true;
  document.addEventListener('keydown', (e) => {
    if (!e.target || e.target.id !== 'dev_path_input' || e.isComposing) return;
    const active = document.querySelector('#dev_path_suggest [data-active="true"]');
    if ((e.key === 'Tab' && !e.shiftKey) || e.key === 'ArrowUp' ||
        e.key === 'ArrowDown' || (e.key === 'Enter' && active)) {
      e.preventDefault();
    }
  }, true);
}
"""
_DEV_SCROLL_ACTIVE_JS = """
setTimeout(() => document.querySelector('#dev_path_suggest [data-active="true"]')
  ?.scrollIntoView({block: 'nearest'}), 0);
"""


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
    for port in app.get("ports", []) or []:
        parts.append(f"-p {port}")
    parts.append(app["github_repo"])
    parts.append(app["app_name"])
    parts.append(app["subdomain"])
    if app.get("env_file"):
        parts.append(app["env_file"])
    return " ".join(parts)


def _expand_home(path: str) -> str:
    """``~`` / ``~/x`` → the host home, like a shell."""
    if HOST_HOME and (path == "~" or path.startswith("~/")):
        return HOST_HOME + path[1:]
    return path


def _browse_root() -> str:
    """The host folder the App Store can list, or "" when it is not mounted."""
    if HOST_HOME and os.path.isdir(HOST_FS_PREFIX + HOST_HOME):
        return HOST_HOME
    return ""


def _under(root: str, path: str) -> bool:
    return path == root or path.startswith(root + "/")


def _host_subdirs(host_dir: str) -> list[str] | None:
    """Sub-folder names of a host folder, or None when it can't be listed.

    Inside the browse root this is a real listing. Its ancestors (``/``,
    ``/Users``, …) list only the next step toward the root, so ``/`` + Tab
    walks down to the home folder.
    """
    root = _browse_root()
    if not root or not host_dir.startswith("/"):
        return None
    d = posixpath.normpath(host_dir)
    if _under(root, d):
        try:
            with os.scandir(HOST_FS_PREFIX + d) as it:
                return sorted((e.name for e in it if e.is_dir()), key=str.lower)
        except OSError:
            return []
    if d == "/" or root.startswith(d + "/"):
        return [root[len(d.rstrip("/")) + 1:].split("/")[0]]
    return None


def _match_subdirs(names: list[str], prefix: str) -> list[str]:
    """Case-insensitive prefix matches; substring matches when there are none.
    Hidden folders only show once the prefix starts with a dot."""
    if not prefix.startswith("."):
        names = [n for n in names if not n.startswith(".")]
    low = prefix.lower()
    head = [n for n in names if n.lower().startswith(low)]
    if head or not low:
        return head
    return [n for n in names if low in n.lower()]


def _project_kind(host_dir: str) -> str:
    """'reflex' (has rxconfig.py), 'python' (has pyproject.toml) or ''."""
    base = HOST_FS_PREFIX + host_dir
    if os.path.isfile(posixpath.join(base, "rxconfig.py")):
        return "reflex"
    if os.path.isfile(posixpath.join(base, "pyproject.toml")):
        return "python"
    return ""


def _fmt(t: Mapping[str, str], key: str, args: Mapping[str, object] | None = None) -> str:
    """``t[key]`` with its ``{placeholders}`` filled in; "" when there is no key.

    A template that does not match its arguments (a slip in a translation) is
    shown as it is rather than breaking the page.
    """
    if not key:
        return ""
    text = t.get(key, key)
    try:
        return text.format(**(args or {}))
    except (KeyError, IndexError, ValueError):
        return text


def _width(percent: int) -> str:
    """A progress bar's CSS width for ``percent``."""
    return f"{max(0, min(100, int(percent)))}%"


def _job_fields_from(data: dict) -> dict:
    """A job's fields from a re-ddns status reply: status, phase, percent, the
    log tail, and its message — a ``msg`` key with ``msg_args``, plus the
    ready-made ``message`` for a key the tables do not have."""
    msg = str(data.get("msg") or "")
    args = data.get("msg_args")
    fields: dict = {
        "key": f"job_{msg}" if msg else "",
        "args": {str(k): str(v) for k, v in args.items()} if isinstance(args, dict) else {},
        "text": str(data.get("message") or ""),
    }
    for k in ("status", "phase"):
        if k in data:
            fields[k] = str(data[k])
    if "percent" in data:
        try:
            fields["percent"] = int(data["percent"])
        except (TypeError, ValueError):
            pass
    log = data.get("log", [])
    if isinstance(log, list):
        fields["log"] = [str(x) for x in log[-14:]]
    return fields


def _localized(entry: Mapping, field: str, code: str) -> str:
    """A catalog text in language ``code``.

    An entry may carry ``"i18n": {"<code>": {"description": "…"}}``; a
    language or field it does not list falls back to the base field.
    """
    text = ((entry.get("i18n") or {}).get(code) or {}).get(field)
    return str(text or entry.get(field, ""))


def _catalog_rows() -> list[dict]:
    """The catalog merged with each app's live Docker status (the grid).

    Each row keeps its entry's ``i18n`` block; ``AppStoreState.apps`` picks
    the texts of the current language from it.
    """
    rows: list[dict] = []
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
                "install_cmd": _build_install_cmd(app),
                "uninstall_cmd": f"./smart_launch.sh --remove={app['subdomain']}",
                "i18n": app.get("i18n") or {},
            }
        )
    return rows


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AppStoreState(LocaleState):
    """Holds the merged catalog + live status and drives all actions.

    The language (``locale``, ``t``) comes from LocaleState, shared with the
    monitor page.  Texts with arguments are kept as a string-table key plus
    the arguments (backend vars) and rendered by the computed vars below.
    """

    _rows: list[dict] = []      # catalog + live status, all languages
    loading: bool = False
    show_langs: bool = False    # the language menu is open

    # The banner, rendered by `message`.
    _msg_key: str = ""
    _msg_args: dict[str, str] = {}
    message_kind: str = "info"  # info | success | error

    # Live install / uninstall jobs, one per app (keyed by subdomain), each
    # followed by its own poller of re-ddns /api/appstore/status/<sub>.
    # Several apps can be installed or removed at the same time: every card
    # shows its own job, and the panel shows the one in ``panel_sub`` (with
    # tabs to switch when there are more).  A job stays listed until it is
    # finished *and* has been looked at: one that finishes behind the panel
    # is dropped (the banner carries the result), unless it failed — then
    # its card says so until the panel for it is opened and closed.  Fields:
    #   sub, name, kind (install | uninstall), status (installing |
    #   uninstalling | installed | uninstalled | error), phase, percent,
    #   log (the tail), seen (the panel showed it), seq (so an old poller of
    #   the same app steps aside), and what the panel says — a string-table
    #   key + args, or the text re-ddns sent when it has no known key
    #   (rendered by `install_message`).
    _jobs: dict[str, dict] = {}
    _job_seq: int = 0
    show_progress: bool = False
    panel_sub: str = ""         # the job the panel shows

    # Uninstall confirmation.
    show_uninstall_confirm: bool = False
    uninstall_sub: str = ""
    uninstall_name: str = ""
    uninstall_container: str = ""
    uninstall_running: bool = False
    uninstall_volumes: list[str] = []
    uninstall_remove_data: bool = False

    # Dynamic env-var config form (for apps that declare "env_schema").
    show_env_form: bool = False
    env_form_sub: str = ""
    env_form_name: str = ""
    _env_items: list[dict] = []        # the entry's env_schema
    _env_i18n: dict = {}               # the entry's i18n block
    _env_missing: list[str] = []       # required keys left empty

    # Dev mode form (local source path).
    show_dev_form: bool = False
    dev_form_sub: str = ""
    dev_form_name: str = ""
    _dev_err_key: str = ""
    _dev_err_args: dict[str, str] = {}
    dev_form_subdir: str = ""
    # Path autocomplete (the input itself is uncontrolled; Tab writes back
    # through rx.set_value).
    dev_path: str = ""
    dev_suggestions: list[dict[str, str]] = []  # {name, kind}
    dev_suggest_more: int = 0                   # matches beyond the list
    dev_suggest_index: int = -1                 # highlighted row, -1 = none
    dev_suggest_open: bool = False
    _dev_status_key: str = ""                   # the line under the path field
    _dev_status_args: dict[str, str] = {}
    dev_path_status_kind: str = ""              # ok | info | warn | error
    dev_browse_root: str = ""

    # The job the panel shows.  Each var reads self._jobs and self.panel_sub
    # itself, so it is recomputed when either changes.

    @rx.var
    def install_status(self) -> str:
        return str((self._jobs.get(self.panel_sub) or {}).get("status", ""))

    @rx.var
    def install_busy(self) -> bool:
        return (self._jobs.get(self.panel_sub) or {}).get("status") in _BUSY

    @rx.var
    def job_kind(self) -> str:
        return str((self._jobs.get(self.panel_sub) or {}).get("kind", "install"))

    @rx.var
    def install_percent(self) -> int:
        return int((self._jobs.get(self.panel_sub) or {}).get("percent", 0))

    @rx.var
    def progress_width(self) -> str:
        return _width(int((self._jobs.get(self.panel_sub) or {}).get("percent", 0)))

    @rx.var
    def install_log(self) -> list[str]:
        return [str(x) for x in (self._jobs.get(self.panel_sub) or {}).get("log", [])]

    @rx.var
    def job_tabs(self) -> list[dict[str, str]]:
        """The jobs the panel can switch between (shown when there are two or more)."""
        return [
            {
                "sub": sub,
                "name": str(job.get("name", sub)),
                "kind": str(job.get("kind", "install")),
                "status": str(job.get("status", "")),
                "percent": str(job.get("percent", 0)),
                "busy": "1" if job.get("status") in _BUSY else "",
                "active": "1" if sub == self.panel_sub else "",
            }
            for sub, job in self._jobs.items()
        ]

    # Texts in the current language.  Each reads self.locale itself, so it is
    # recomputed when the language changes, on this page or the other one.

    @rx.var
    def apps(self) -> list[dict[str, str]]:
        """The grid rows, each description in the current language, plus the
        app's live job: ``job_busy`` "1" while it installs or uninstalls,
        ``job_error`` "1" when that failed, and its kind and percent."""
        code = self.locale
        jobs = self._jobs
        rows: list[dict[str, str]] = []
        for row in self._rows:
            job = jobs.get(row["subdomain"]) or {}
            pct = int(job.get("percent", 0))
            rows.append(
                {
                    **{k: v for k, v in row.items() if k != "i18n"},
                    "description": _localized(row, "description", code),
                    "job_busy": "1" if job.get("status") in _BUSY else "",
                    "job_error": "1" if job.get("status") == "error" else "",
                    "job_kind": str(job.get("kind", "install")),
                    "job_percent": str(pct),
                    "job_width": _width(pct),
                }
            )
        return rows

    @rx.var
    def message(self) -> str:
        return _fmt(i18n.strings(self.locale), self._msg_key, self._msg_args)

    @rx.var
    def install_message(self) -> str:
        job = self._jobs.get(self.panel_sub) or {}
        t = i18n.strings(self.locale)
        key = str(job.get("key", ""))
        if key not in t:
            return str(job.get("text", ""))
        args = dict(job.get("args") or {})
        if "phase" in args:
            args["phase"] = t.get(f"phase_{args['phase']}", args["phase"])
        return _fmt(t, key, args)

    @rx.var
    def progress_title(self) -> str:
        job = self._jobs.get(self.panel_sub) or {}
        key = "job_title_uninstall" if job.get("kind") == "uninstall" else "job_title_install"
        return _fmt(
            i18n.strings(self.locale), key, {"name": job.get("name", self.panel_sub)}
        )

    @rx.var
    def uninstall_title(self) -> str:
        return _fmt(i18n.strings(self.locale), "un_title", {"name": self.uninstall_name})

    @rx.var
    def uninstall_body(self) -> list[str]:
        """The explanation, split around ``{container}`` (shown as code)."""
        before, _, after = i18n.strings(self.locale)["un_body"].partition("{container}")
        return [before, after]

    @rx.var
    def uninstall_volume_list(self) -> str:
        return i18n.strings(self.locale)["list_sep"].join(self.uninstall_volumes)

    @rx.var
    def env_form_title(self) -> str:
        return _fmt(i18n.strings(self.locale), "env_title", {"name": self.env_form_name})

    @rx.var
    def env_form_schema(self) -> list[dict[str, str]]:
        """The settings form's fields, their texts in the current language.

        Translations sit in the entry's i18n block under
        ``"<code>": {"env": {"<KEY>": {"label", "placeholder", "help"}}}``.
        """
        own = ((self._env_i18n.get(self.locale) or {}).get("env")) or {}
        rows: list[dict[str, str]] = []
        for item in self._env_items:
            key = str(item.get("key", ""))
            tr = own.get(key) or {}
            rows.append(
                {
                    "key": key,
                    "label": str(tr.get("label") or item.get("label") or key),
                    "placeholder": str(tr.get("placeholder") or item.get("placeholder", "")),
                    "help": str(tr.get("help") or item.get("help", "")),
                    "secret": "1" if item.get("secret") else "",
                    "required": "1" if item.get("required", True) else "",
                }
            )
        return rows

    @rx.var
    def env_form_error(self) -> str:
        if not self._env_missing:
            return ""
        t = i18n.strings(self.locale)
        labels = {row["key"]: row["label"] for row in self.env_form_schema}
        fields = t["list_sep"].join(labels.get(k, k) for k in self._env_missing)
        return _fmt(t, "env_missing", {"fields": fields})

    @rx.var
    def dev_form_title(self) -> str:
        return _fmt(i18n.strings(self.locale), "dev_title", {"name": self.dev_form_name})

    @rx.var
    def dev_form_error(self) -> str:
        return _fmt(i18n.strings(self.locale), self._dev_err_key, self._dev_err_args)

    @rx.var
    def dev_path_status(self) -> str:
        return _fmt(i18n.strings(self.locale), self._dev_status_key, self._dev_status_args)

    @rx.var
    def dev_suggest_more_text(self) -> str:
        return _fmt(i18n.strings(self.locale), "dev_more", {"count": self.dev_suggest_more})

    def _say(self, key: str, kind: str = "info", **args) -> None:
        """Show ``t[key]`` (with ``args``) in the banner; "" hides it."""
        self._msg_key = key
        self._msg_args = {k: str(v) for k, v in args.items()}
        self.message_kind = kind

    def _job_update(self, sub: str, **fields) -> None:
        """Change a job's fields.  ``_jobs`` is reassigned (not mutated) so
        that every var reading it is recomputed."""
        job = self._jobs.get(sub)
        if job is not None:
            self._jobs = {**self._jobs, sub: {**job, **fields}}

    def _begin_job(self, sub: str, name: str, kind: str, key: str) -> int:
        """Start following a new job for ``sub`` and show it in the panel;
        ``t[key]`` is what the panel says until re-ddns answers.

        Returns the job's sequence number.  A poller whose number the job no
        longer carries (the same app was started again) steps aside.
        """
        self._job_seq += 1
        self._jobs = {
            **self._jobs,
            sub: {
                "sub": sub,
                "name": name,
                "kind": kind,
                "status": "uninstalling" if kind == "uninstall" else "installing",
                "phase": "queued",
                "percent": 2,
                "log": [],
                "key": key,
                "args": {},
                "text": "",
                "seen": True,
                "seq": self._job_seq,
            },
        }
        self.panel_sub = sub
        self.show_progress = True
        self._say("")
        return self._job_seq

    def _job_failed(self, sub: str, key: str, **args) -> None:
        """The request itself failed: ``t[key]`` (with ``args``) is the error."""
        self._job_update(
            sub,
            status="error",
            key=key,
            args={k: str(v) for k, v in args.items()},
            text="",
        )

    # ── language menu ──

    @rx.event
    def set_locale(self, code: str):
        """Every text on the page is a computed var, so this is all it takes."""
        self._set_locale(code)
        self.show_langs = False

    @rx.event
    def toggle_langs(self):
        self.show_langs = not self.show_langs

    @rx.event
    def close_langs(self):
        self.show_langs = False

    def _lookup(self, subdomain: str) -> dict | None:
        for app in _load_catalog():
            if app["subdomain"] == subdomain:
                return app
        return None

    @rx.event
    def refresh(self):
        """Reload catalog and recompute each app's live status."""
        self.loading = True
        self._say("")
        yield
        self._rows = _catalog_rows()
        self.loading = False

    @rx.event
    def start_app(self, subdomain: str):
        app = self._lookup(subdomain)
        if not app:
            return
        name = _container_name(app)
        r = _docker_request("POST", f"/containers/{name}/start")
        if r is None:
            self._say("store_no_socket_start", "error")
        elif r.status_code in (204, 304):
            self._say("store_started", "success", name=name)
        elif r.status_code == 404:
            self._say("store_not_installed_yet", "error", name=name)
        else:
            self._say("store_start_failed", "error", code=r.status_code)
        yield AppStoreState.refresh

    @rx.event
    def stop_app(self, subdomain: str):
        app = self._lookup(subdomain)
        if not app:
            return
        name = _container_name(app)
        r = _docker_request("POST", f"/containers/{name}/stop")
        if r is None:
            self._say("store_no_socket_stop", "error")
        elif r.status_code in (204, 304):
            self._say("store_stopped", "success", name=name)
        else:
            self._say("store_stop_failed", "error", code=r.status_code)
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
        schema = [item for item in app.get("env_schema") or [] if item.get("key")]
        if schema:
            self.env_form_sub = subdomain
            self.env_form_name = str(app.get("name", subdomain))
            self._env_missing = []
            self._env_items = schema
            self._env_i18n = app.get("i18n") or {}
            self.show_env_form = True
            return
        return AppStoreState.install_app(subdomain, {})

    @rx.event
    def cancel_env_form(self):
        self.show_env_form = False
        self.env_form_sub = ""
        self._env_items = []
        self._env_missing = []

    @rx.event
    def submit_env_form(self, form_data: dict):
        """Validate the required settings, then kick off the install."""
        sub = self.env_form_sub
        missing = [
            item["key"]
            for item in self.env_form_schema
            if item.get("required") == "1"
            and not str(form_data.get(item["key"], "")).strip()
        ]
        if missing:
            self._env_missing = missing
            return
        env = {
            k: str(v)
            for k, v in form_data.items()
            if str(v).strip() != ""
        }
        self.show_env_form = False
        self._env_missing = []
        return AppStoreState.install_app(sub, env)

    @rx.event
    def install_app(self, subdomain: str, env: dict[str, str] | None = None):
        """Ask re-ddns to install the app, then poll progress in-page."""
        app = self._lookup(subdomain)
        if not app:
            return
        display = str(app.get("name", subdomain))
        seq = self._begin_job(subdomain, display, "install", "job_sending_install")

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
            "extra_repos": app.get("extra_repos") or [],
            "ports": app.get("ports") or [],
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(f"{RE_DDNS_API_URL}/api/appstore/install", json=spec)
            if r.status_code != 200:
                self._job_failed(
                    subdomain, "job_install_refused", code=r.status_code, detail=r.text[:200]
                )
                return
        except Exception as exc:  # noqa: BLE001
            self._job_failed(subdomain, "job_unreachable", error=exc)
            return
        # Kick off background polling.
        return AppStoreState.poll_progress(subdomain, seq)

    @rx.event(background=True)
    async def poll_progress(self, sub: str, seq: int):
        """Poll re-ddns for one job's progress until it finishes or fails.

        Every job has its own poller, so several apps can be installed or
        removed at the same time.  Closing the panel does not stop this: the
        job carries on in re-ddns, the card keeps showing its progress, and
        the grid refreshes at the end.
        """
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
                job = self._jobs.get(sub)
                if not job or job.get("seq") != seq:
                    return  # the app was started again; its new poller took over
                if data:
                    self._job_update(sub, **_job_fields_from(data))
                    job = self._jobs[sub]
                status = str(job.get("status", ""))
                name = str(job.get("name", sub))

            if status in ("installed", "uninstalled", "error"):
                # Reload the grid here rather than through `refresh`, which
                # would wipe the banner set below.
                rows = await asyncio.to_thread(_catalog_rows)
                async with self:
                    job = self._jobs.get(sub)
                    if not job or job.get("seq") != seq:
                        return
                    self._rows = rows
                    if status == "installed":
                        self._say("store_installed", "success", name=name)
                    elif status == "uninstalled":
                        self._say("store_uninstalled", "success", name=name)
                    if not (self.show_progress and self.panel_sub == sub):
                        # Finished behind the panel: a success is told by the
                        # banner and forgotten; a failure stays on its card
                        # until it has been looked at.
                        if status == "error":
                            self._job_update(sub, seen=False)
                        else:
                            self._jobs = {k: v for k, v in self._jobs.items() if k != sub}
                return

            await asyncio.sleep(1.5)

    @rx.event
    def ask_uninstall(self, subdomain: str):
        """Uninstall button: say what will go and ask for confirmation."""
        app = self._lookup(subdomain)
        if not app:
            return
        name = _container_name(app)
        running, volumes = False, []
        r = _docker_request("GET", f"/containers/{name}/json")
        if r is not None and r.status_code == 200:
            try:
                info = r.json()
                running = info.get("State", {}).get("Status") in ("running", "paused", "restarting")
                volumes = sorted({
                    m["Name"] for m in info.get("Mounts", [])
                    if m.get("Type") == "volume" and m.get("Name")
                })
            except Exception:  # noqa: BLE001
                pass
        self.uninstall_sub = subdomain
        self.uninstall_name = str(app.get("name", subdomain))
        self.uninstall_container = name
        self.uninstall_running = running
        self.uninstall_volumes = volumes
        self.uninstall_remove_data = False
        self.show_uninstall_confirm = True

    @rx.event
    def cancel_uninstall(self):
        self.show_uninstall_confirm = False
        self.uninstall_sub = ""

    @rx.event
    def set_uninstall_remove_data(self, value: bool):
        self.uninstall_remove_data = bool(value)

    @rx.event
    def confirm_uninstall(self):
        sub, remove_data = self.uninstall_sub, self.uninstall_remove_data
        self.show_uninstall_confirm = False
        self.uninstall_sub = ""
        if sub:
            return AppStoreState.uninstall_app(sub, remove_data)

    @rx.event
    def uninstall_app(self, subdomain: str, remove_data: bool = False):
        """Ask re-ddns to uninstall the app, then follow its progress in-page.

        re-ddns stops and deletes the container, then drops the registry
        entry, DNS record, nginx config and TLS certificate, one step per
        status poll — the same panel as an install shows each step.
        """
        app = self._lookup(subdomain)
        display = str(app.get("name", subdomain)) if app else subdomain
        seq = self._begin_job(subdomain, display, "uninstall", "job_sending_uninstall")

        spec = {
            "subdomain": subdomain,
            "name": display,
            "zone": SERVICE_ZONE,
            "remove_data": bool(remove_data),
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(f"{RE_DDNS_API_URL}/api/appstore/uninstall", json=spec)
            if r.status_code != 200:
                self._job_failed(
                    subdomain, "job_uninstall_refused", code=r.status_code, detail=r.text[:200]
                )
                return
        except Exception as exc:  # noqa: BLE001
            self._job_failed(subdomain, "job_unreachable", error=exc)
            return
        return AppStoreState.poll_progress(subdomain, seq)

    @rx.event
    def close_progress(self):
        """Hide the panel.  A job still running carries on and its card shows
        it.  Finished jobs that have been looked at are forgotten; a failure
        nobody has opened yet stays on its card."""
        self.show_progress = False
        self._jobs = {
            sub: job
            for sub, job in self._jobs.items()
            if job.get("status") in _BUSY
            or (job.get("status") == "error" and not job.get("seen"))
        }

    @rx.event
    def open_progress(self, sub: str):
        """Show one app's job in the panel: a card's "View progress" button,
        or a tab in the panel."""
        if sub in self._jobs:
            self._job_update(sub, seen=True)
            self.panel_sub = sub
            self.show_progress = True

    # ── Dev mode ──

    @rx.event
    def begin_dev_install(self, subdomain: str):
        """Open the dev-mode form to collect the local source path."""
        app = self._lookup(subdomain)
        if not app:
            return
        self.dev_form_sub = subdomain
        self.dev_form_name = str(app.get("name", subdomain))
        self._dev_err_key = ""
        self.dev_form_subdir = str(app.get("subdir") or "").strip("/")
        self.dev_browse_root = _browse_root()
        self.dev_path = ""
        self.dev_suggest_index = -1
        self._refresh_dev_suggestions()
        self.show_dev_form = True
        return rx.call_script(_DEV_PATH_KEYS_JS)

    @rx.event
    def cancel_dev_form(self):
        self.show_dev_form = False
        self.dev_form_sub = ""
        self._dev_err_key = ""

    def _split_dev_path(self) -> tuple[str, str]:
        """``/a/b/pre`` → (``/a/b/``, ``pre``). Empty path → (``/``, "")."""
        path = _expand_home(self.dev_path.strip()) or "/"
        if "/" not in path:
            return "", path
        head, _, prefix = path.rpartition("/")
        return head + "/", prefix

    def _refresh_dev_suggestions(self):
        """Recompute the suggestion list and the hint for the typed path."""
        head, prefix = self._split_dev_path()
        names = _host_subdirs(head) if head else None
        matches = _match_subdirs(names or [], prefix) if self.dev_path.strip() else []
        shown = matches[:DEV_SUGGEST_LIMIT]
        self.dev_suggestions = [
            {"name": n, "kind": _project_kind(head + n)} for n in shown
        ]
        self.dev_suggest_more = len(matches) - len(shown)
        if self.dev_suggest_index >= len(shown):
            self.dev_suggest_index = -1

        root = self.dev_browse_root
        path = _expand_home(self.dev_path.strip())
        key, kind, args = "", "", {}
        if not root or not path:
            pass
        elif not path.startswith("/"):
            key, kind = "dev_st_relative", "error"
        else:
            d = posixpath.normpath(path)
            if not _under(root, d):
                if names is None:
                    key, kind, args = "dev_st_outside", "warn", {"root": root}
                elif not matches:
                    key, kind = "dev_st_not_found", "error"
            elif os.path.isdir(HOST_FS_PREFIX + d):
                sub = self.dev_form_subdir
                project = posixpath.join(d, sub) if sub else d
                proj_kind = _project_kind(project)
                if proj_kind == "reflex":
                    key, kind = "dev_st_reflex", "ok"
                elif proj_kind == "python":
                    key, kind = "dev_st_python", "ok"
                else:
                    key, kind = "dev_st_none", "info"
                if sub:
                    key, args = key + "_sub", {"sub": sub}
            elif not matches:
                key, kind = "dev_st_not_found", "error"
        self._dev_status_key, self._dev_status_args = key, args
        self.dev_path_status_kind = kind

    def _set_dev_path(self, path: str):
        """Write a completed path back into the input and refresh."""
        self.dev_path = path
        self.dev_suggest_index = -1
        self.dev_suggest_open = True
        self._refresh_dev_suggestions()
        return [
            rx.set_value("dev_path_input", path),
            rx.set_focus("dev_path_input"),
        ]

    def _accept_dev_dir(self, name: str):
        head, _ = self._split_dev_path()
        return self._set_dev_path(head + name + "/")

    def _complete_dev_path(self):
        """Tab: like a shell, plus a highlight you can confirm with Tab again."""
        if 0 <= self.dev_suggest_index < len(self.dev_suggestions):
            return self._accept_dev_dir(self.dev_suggestions[self.dev_suggest_index]["name"])
        if not self.dev_path.strip():
            return self._set_dev_path("/")
        head, prefix = self._split_dev_path()
        matches = _match_subdirs(_host_subdirs(head) or [], prefix) if head else []
        if len(matches) == 1:
            return self._accept_dev_dir(matches[0])
        if not matches:
            return
        # Extend to the longest common prefix (case-insensitive) …
        common = os.path.commonprefix([m.lower() for m in matches])
        if common.startswith(prefix.lower()) and len(common) > len(prefix):
            return self._set_dev_path(head + matches[0][: len(common)])
        # … otherwise highlight the first match; the next Tab takes it.
        self.dev_suggest_open = True
        self.dev_suggest_index = 0
        return rx.call_script(_DEV_SCROLL_ACTIVE_JS)

    @rx.event
    def on_dev_path_change(self, value: str):
        self.dev_path = value
        self.dev_suggest_index = -1
        self.dev_suggest_open = True
        self._refresh_dev_suggestions()

    @rx.event
    def on_dev_path_key(self, key: str, info: rx.event.KeyInputInfo):
        if key == "Tab" and not info.get("shift_key"):
            return self._complete_dev_path()
        if key in ("ArrowDown", "ArrowUp"):
            n = len(self.dev_suggestions)
            if not n:
                return
            self.dev_suggest_open = True
            step = 1 if key == "ArrowDown" else -1
            if self.dev_suggest_index < 0:
                self.dev_suggest_index = 0 if step > 0 else n - 1
            else:
                self.dev_suggest_index = (self.dev_suggest_index + step) % n
            return rx.call_script(_DEV_SCROLL_ACTIVE_JS)
        if key == "Enter" and self.dev_suggest_index >= 0:
            return self._complete_dev_path()
        if key == "Escape":
            self.dev_suggest_open = False
            self.dev_suggest_index = -1

    @rx.event
    def pick_dev_suggestion(self, name: str):
        return self._accept_dev_dir(name)

    @rx.event
    def submit_dev_form(self, form_data: dict):
        """Validate local_path then kick off the dev install."""
        local_path = _expand_home(str(form_data.get("local_path", "")).strip())
        if local_path != "/":
            local_path = local_path.rstrip("/")
        if not local_path:
            self._dev_err_key, self._dev_err_args = "dev_err_empty", {}
            return
        root = self.dev_browse_root
        d = posixpath.normpath(local_path)
        if root and _under(root, d) and not os.path.isdir(HOST_FS_PREFIX + d):
            self._dev_err_key, self._dev_err_args = "dev_err_missing", {"path": local_path}
            return
        self.show_dev_form = False
        self._dev_err_key = ""
        return AppStoreState.dev_install_app(self.dev_form_sub, local_path)

    @rx.event
    def dev_install_app(self, subdomain: str, local_path: str):
        """Ask re-ddns to do a dev-mode install (bind-mount, no clone)."""
        app = self._lookup(subdomain)
        if not app:
            return
        display = str(app.get("name", subdomain))
        seq = self._begin_job(subdomain, display, "install", "job_sending_dev_install")

        spec = {
            "subdomain": subdomain,
            "app_name": app["app_name"],
            "local_path": local_path,
            "name": display,
            "subdir": app.get("subdir") or "",
            "zone": SERVICE_ZONE,
            "volumes": app.get("volumes") or [],
            "env_file": app.get("env_file") or "",
            "env": {},
            "extra_repos": app.get("extra_repos") or [],
            "ports": app.get("ports") or [],
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(f"{RE_DDNS_API_URL}/api/appstore/dev-install", json=spec)
            if r.status_code != 200:
                self._job_failed(
                    subdomain, "job_dev_install_refused", code=r.status_code, detail=r.text[:200]
                )
                return
        except Exception as exc:  # noqa: BLE001
            self._job_failed(subdomain, "job_unreachable", error=exc)
            return
        return AppStoreState.poll_progress(subdomain, seq)


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
        rx.el.span(
            rx.match(
                app["status"],
                ("running", AppStoreState.t["st_running"]),
                ("stopped", AppStoreState.t["st_stopped"]),
                ("not_installed", AppStoreState.t["st_not_installed"]),
                AppStoreState.t["st_unknown"],
            ),
            # One line: CJK labels would otherwise break mid-word
            # (未インスト/ール) when a long app name squeezes the badge.
            class_name="text-xs font-bold whitespace-nowrap",
        ),
        class_name=rx.match(
            app["status"],
            (
                "running",
                "flex shrink-0 items-center gap-2 px-3 py-1 rounded-full bg-green-50 text-green-700",
            ),
            (
                "stopped",
                "flex shrink-0 items-center gap-2 px-3 py-1 rounded-full bg-yellow-50 text-yellow-700",
            ),
            (
                "not_installed",
                "flex shrink-0 items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-500",
            ),
            "flex shrink-0 items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-500",
        ),
    )


def _btn(label, icon: str, on_click, color: str) -> rx.Component:
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
            rx.el.span(AppStoreState.t["store_open"]),
            class_name="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold bg-blue-600 text-white hover:bg-blue-700 transition-all",
        ),
        href=app["url"],
        is_external=True,
    )


def _dev_btn(app: rx.Var[dict]) -> rx.Component:
    if not DEV_MODE_ENABLED:
        return rx.fragment()
    return _btn(
        AppStoreState.t["store_dev"],
        "code",
        lambda: AppStoreState.begin_dev_install(app["subdomain"]),
        "bg-purple-50 text-purple-700 hover:bg-purple-100",
    )


def job_indicator(app: rx.Var[dict]) -> rx.Component:
    """What a card shows while its app is being installed or removed — its
    own progress bar, so several cards can run side by side — or after that
    failed (until the panel for it has been opened and closed)."""
    is_uninstall = app["job_kind"] == "uninstall"
    failed = app["job_error"] == "1"
    return rx.el.div(
        rx.el.div(
            rx.cond(
                failed,
                rx.icon("circle-alert", class_name="h-4 w-4"),
                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
            ),
            rx.el.span(
                rx.cond(
                    failed,
                    rx.cond(
                        is_uninstall,
                        AppStoreState.t["store_uninstall_failed"],
                        AppStoreState.t["store_install_failed"],
                    ),
                    rx.fragment(
                        rx.cond(
                            is_uninstall,
                            AppStoreState.t["store_uninstalling"],
                            AppStoreState.t["store_installing"],
                        ),
                        " ",
                        app["job_percent"],
                        "%",
                    ),
                ),
                class_name="text-sm font-semibold",
            ),
            rx.el.button(
                AppStoreState.t["store_view_progress"],
                on_click=lambda: AppStoreState.open_progress(app["subdomain"]),
                class_name="ml-auto px-3 py-1.5 rounded-xl text-xs font-semibold bg-gray-900 text-white hover:bg-black",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.div(
            rx.el.div(
                class_name=rx.cond(
                    failed,
                    "h-full bg-red-500 transition-all duration-500",
                    rx.cond(
                        is_uninstall,
                        "h-full bg-orange-500 transition-all duration-500",
                        "h-full bg-blue-600 transition-all duration-500",
                    ),
                ),
                style={"width": app["job_width"]},
            ),
            class_name="w-full h-1.5 bg-white/80 rounded-full overflow-hidden mt-2",
        ),
        class_name=rx.cond(
            failed | is_uninstall,
            "px-3 py-2 rounded-xl bg-red-50 text-red-700",
            "px-3 py-2 rounded-xl bg-blue-50 text-blue-700",
        ),
    )


def action_buttons(app: rx.Var[dict]) -> rx.Component:
    has_job = (app["job_busy"] == "1") | (app["job_error"] == "1")
    return rx.cond(has_job, job_indicator(app), _action_buttons(app))


def _action_buttons(app: rx.Var[dict]) -> rx.Component:
    return rx.match(
        app["status"],
        (
            "running",
            rx.el.div(
                open_button(app),
                _btn(
                    AppStoreState.t["store_stop"],
                    "square",
                    lambda: AppStoreState.stop_app(app["subdomain"]),
                    "bg-yellow-50 text-yellow-700 hover:bg-yellow-100",
                ),
                _btn(
                    AppStoreState.t["store_uninstall"],
                    "trash-2",
                    lambda: AppStoreState.ask_uninstall(app["subdomain"]),
                    "bg-red-50 text-red-600 hover:bg-red-100",
                ),
                _dev_btn(app),
                class_name="flex flex-wrap items-center gap-2",
            ),
        ),
        (
            "stopped",
            rx.el.div(
                _btn(
                    AppStoreState.t["store_start"],
                    "play",
                    lambda: AppStoreState.start_app(app["subdomain"]),
                    "bg-green-600 text-white hover:bg-green-700",
                ),
                _btn(
                    AppStoreState.t["store_uninstall"],
                    "trash-2",
                    lambda: AppStoreState.ask_uninstall(app["subdomain"]),
                    "bg-red-50 text-red-600 hover:bg-red-100",
                ),
                _dev_btn(app),
                class_name="flex flex-wrap items-center gap-2",
            ),
        ),
        # not_installed / unknown
        rx.el.div(
            _btn(
                AppStoreState.t["store_install"],
                "download",
                lambda: AppStoreState.begin_install(app["subdomain"]),
                "bg-gray-900 text-white hover:bg-black",
            ),
            _dev_btn(app),
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
                            AppStoreState.env_form_title,
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
                    AppStoreState.t["env_intro"],
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
                            AppStoreState.t["cancel"],
                            type="button",
                            on_click=AppStoreState.cancel_env_form,
                            class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200",
                        ),
                        rx.el.button(
                            rx.icon("download", class_name="h-4 w-4"),
                            rx.el.span(AppStoreState.t["store_install"]),
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


def dev_suggestion_row(item: rx.Var[dict], index: rx.Var[int]) -> rx.Component:
    active = index == AppStoreState.dev_suggest_index
    return rx.el.div(
        rx.icon("folder", class_name="h-4 w-4 shrink-0 text-purple-400"),
        rx.el.span(item["name"], class_name="truncate"),
        rx.match(
            item["kind"],
            (
                "reflex",
                rx.el.span(
                    "Reflex",
                    class_name="ml-auto shrink-0 px-2 rounded-full bg-purple-100 text-purple-700 text-[10px] font-sans font-bold",
                ),
            ),
            (
                "python",
                rx.el.span(
                    "pyproject",
                    class_name="ml-auto shrink-0 px-2 rounded-full bg-gray-100 text-gray-600 text-[10px] font-sans font-bold",
                ),
            ),
            rx.fragment(),
        ),
        on_click=AppStoreState.pick_dev_suggestion(item["name"]),
        custom_attrs={"data-active": rx.cond(active, "true", "false")},
        class_name=rx.cond(
            active,
            "flex items-center gap-2 px-3 py-1.5 cursor-pointer bg-purple-100 text-purple-900",
            "flex items-center gap-2 px-3 py-1.5 cursor-pointer text-gray-700 hover:bg-gray-50",
        ),
    )


def dev_path_suggestions() -> rx.Component:
    """Folder list under the Dev path input (filtered as you type)."""
    return rx.cond(
        AppStoreState.dev_suggest_open & (AppStoreState.dev_suggestions.length() > 0),
        rx.el.div(
            rx.foreach(AppStoreState.dev_suggestions, dev_suggestion_row),
            rx.cond(
                AppStoreState.dev_suggest_more > 0,
                rx.el.div(
                    AppStoreState.dev_suggest_more_text,
                    class_name="px-3 py-1.5 text-xs font-sans text-gray-400",
                ),
                rx.fragment(),
            ),
            id="dev_path_suggest",
            class_name="mt-1 max-h-56 overflow-y-auto border border-gray-200 rounded-xl text-sm font-mono bg-white",
        ),
        rx.fragment(),
    )


def dev_form_panel() -> rx.Component:
    """Modal form to collect the local source path for dev-mode install."""
    return rx.cond(
        AppStoreState.show_dev_form,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("code", class_name="h-6 w-6 text-purple-600"),
                        rx.el.h3(
                            AppStoreState.dev_form_title,
                            class_name="text-lg font-bold text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-5 w-5"),
                        on_click=AppStoreState.cancel_dev_form,
                        class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg",
                    ),
                    class_name="flex items-center justify-between mb-2",
                ),
                rx.el.p(
                    AppStoreState.t["dev_intro"],
                    class_name="text-sm text-gray-500 mb-4",
                ),
                rx.cond(
                    AppStoreState.dev_form_error != "",
                    rx.el.div(
                        AppStoreState.dev_form_error,
                        class_name="p-3 mb-4 bg-red-50 text-red-700 rounded-xl text-sm border border-red-100",
                    ),
                    rx.fragment(),
                ),
                rx.form(
                    rx.el.div(
                        rx.el.label(
                            AppStoreState.t["dev_path_label"],
                            rx.el.span(" *", class_name="text-red-500"),
                            class_name="text-sm font-semibold text-gray-700",
                        ),
                        rx.el.input(
                            id="dev_path_input",
                            name="local_path",
                            placeholder=AppStoreState.t["dev_path_placeholder"],
                            type="text",
                            auto_complete="off",
                            spell_check=False,
                            auto_focus=True,
                            on_change=AppStoreState.on_dev_path_change,
                            on_key_down=AppStoreState.on_dev_path_key,
                            class_name="mt-1 w-full px-3 py-2 border border-gray-200 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500",
                        ),
                        dev_path_suggestions(),
                        rx.cond(
                            AppStoreState.dev_path_status != "",
                            rx.el.p(
                                AppStoreState.dev_path_status,
                                class_name=rx.match(
                                    AppStoreState.dev_path_status_kind,
                                    ("ok", "text-xs text-green-700 mt-1"),
                                    ("warn", "text-xs text-amber-700 mt-1"),
                                    ("error", "text-xs text-red-600 mt-1"),
                                    "text-xs text-gray-500 mt-1",
                                ),
                            ),
                            rx.fragment(),
                        ),
                        rx.el.p(
                            AppStoreState.t["dev_path_hint"],
                            rx.cond(
                                AppStoreState.dev_browse_root != "",
                                rx.el.span(AppStoreState.t["dev_path_keys"]),
                                rx.el.span(AppStoreState.t["dev_path_no_browse"]),
                            ),
                            class_name="text-xs text-gray-400 mt-1",
                        ),
                        class_name="flex flex-col",
                    ),
                    rx.el.div(
                        rx.el.button(
                            AppStoreState.t["cancel"],
                            type="button",
                            on_click=AppStoreState.cancel_dev_form,
                            class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200",
                        ),
                        rx.el.button(
                            rx.icon("code", class_name="h-4 w-4"),
                            rx.el.span(AppStoreState.t["dev_install"]),
                            type="submit",
                            class_name="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white font-semibold rounded-xl hover:bg-purple-700",
                        ),
                        class_name="flex justify-end gap-2 mt-6",
                    ),
                    on_submit=AppStoreState.submit_dev_form,
                    reset_on_submit=False,
                ),
                class_name="w-full max-w-lg bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6",
        ),
        None,
    )


def uninstall_confirm_panel() -> rx.Component:
    """Asked by the Uninstall button: what goes, and whether the data goes too."""
    return rx.cond(
        AppStoreState.show_uninstall_confirm,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("trash-2", class_name="h-6 w-6 text-red-600"),
                        rx.el.h3(
                            AppStoreState.uninstall_title,
                            class_name="text-lg font-bold text-gray-900",
                        ),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-5 w-5"),
                        on_click=AppStoreState.cancel_uninstall,
                        class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg",
                    ),
                    class_name="flex items-center justify-between mb-2",
                ),
                rx.el.p(
                    AppStoreState.uninstall_body[0],
                    rx.el.code(
                        AppStoreState.uninstall_container,
                        class_name="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded",
                    ),
                    AppStoreState.uninstall_body[1],
                    class_name="text-sm text-gray-600 mb-3 leading-relaxed",
                ),
                rx.cond(
                    AppStoreState.uninstall_running,
                    rx.el.p(
                        AppStoreState.t["un_running"],
                        class_name="p-3 mb-3 bg-amber-50 text-amber-800 rounded-xl text-sm border border-amber-100",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    AppStoreState.uninstall_volumes.length() > 0,
                    rx.el.div(
                        rx.checkbox(
                            AppStoreState.t["un_remove_data"],
                            checked=AppStoreState.uninstall_remove_data,
                            on_change=AppStoreState.set_uninstall_remove_data,
                            color_scheme="red",
                            class_name="text-sm font-semibold text-gray-800",
                        ),
                        rx.el.p(
                            AppStoreState.uninstall_volume_list,
                            class_name="text-xs font-mono text-gray-500 mt-1 ml-6",
                        ),
                        rx.el.p(
                            AppStoreState.t["un_keep_hint"],
                            class_name="text-xs text-gray-500 mt-1 ml-6",
                        ),
                        class_name="p-3 mb-3 rounded-xl border border-gray-200",
                    ),
                    rx.fragment(),
                ),
                rx.el.div(
                    rx.el.button(
                        AppStoreState.t["cancel"],
                        type="button",
                        on_click=AppStoreState.cancel_uninstall,
                        class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200",
                    ),
                    rx.el.button(
                        rx.icon("trash-2", class_name="h-4 w-4"),
                        rx.el.span(AppStoreState.t["un_confirm"]),
                        type="button",
                        on_click=AppStoreState.confirm_uninstall,
                        class_name="flex items-center gap-2 px-4 py-2 bg-red-600 text-white font-semibold rounded-xl hover:bg-red-700",
                    ),
                    class_name="flex justify-end gap-2 mt-2",
                ),
                class_name="w-full max-w-lg bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6",
        ),
        None,
    )


def job_tab(job: rx.Var[dict]) -> rx.Component:
    """One job in the panel's switcher: its name and percent; click shows it."""
    return rx.el.button(
        rx.cond(
            job["busy"] == "1",
            rx.icon("loader-circle", class_name="h-3.5 w-3.5 animate-spin"),
            rx.cond(
                job["status"] == "error",
                rx.icon("circle-alert", class_name="h-3.5 w-3.5"),
                rx.icon("check", class_name="h-3.5 w-3.5"),
            ),
        ),
        rx.el.span(job["name"]),
        rx.el.span(job["percent"], "%", class_name="opacity-70"),
        on_click=lambda: AppStoreState.open_progress(job["sub"]),
        class_name=rx.cond(
            job["active"] == "1",
            "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-gray-900 text-white",
            "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200",
        ),
    )


def progress_panel() -> rx.Component:
    return rx.cond(
        AppStoreState.show_progress,
        rx.el.div(
            rx.el.div(
                # Header
                rx.el.div(
                    rx.el.div(
                        rx.cond(
                            AppStoreState.install_status == "error",
                            rx.icon("circle-alert", class_name="h-6 w-6 text-red-600"),
                            rx.cond(
                                AppStoreState.install_busy,
                                rx.icon(
                                    "loader-circle",
                                    class_name=rx.cond(
                                        AppStoreState.job_kind == "uninstall",
                                        "h-6 w-6 text-red-600 animate-spin",
                                        "h-6 w-6 text-blue-600 animate-spin",
                                    ),
                                ),
                                rx.icon("circle-check-big", class_name="h-6 w-6 text-green-600"),
                            ),
                        ),
                        rx.el.h3(
                            AppStoreState.progress_title,
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
                # The other jobs in flight (when there are several)
                rx.cond(
                    AppStoreState.job_tabs.length() > 1,
                    rx.el.div(
                        rx.foreach(AppStoreState.job_tabs, job_tab),
                        class_name="flex flex-wrap gap-2 mb-4",
                    ),
                    None,
                ),
                # Progress bar
                rx.el.div(
                    rx.el.div(
                        class_name=rx.cond(
                            AppStoreState.install_status == "error",
                            "h-full bg-red-500 transition-all duration-500",
                            rx.cond(
                                AppStoreState.job_kind == "uninstall",
                                "h-full bg-orange-500 transition-all duration-500",
                                "h-full bg-blue-600 transition-all duration-500",
                            ),
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
                            rx.cond(
                                AppStoreState.job_kind == "uninstall",
                                AppStoreState.t["job_busy_uninstall"],
                                AppStoreState.t["job_busy_install"],
                            ),
                            on_click=AppStoreState.close_progress,
                            class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200",
                        ),
                        rx.el.button(
                            AppStoreState.t["job_done"],
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


def lang_backdrop() -> rx.Component:
    """Invisible layer behind the open language menu: a click elsewhere closes it."""
    return rx.cond(
        AppStoreState.show_langs,
        rx.el.div(on_click=AppStoreState.close_langs, class_name="fixed inset-0 z-10"),
        None,
    )


def index() -> rx.Component:
    return rx.el.main(
        lang_backdrop(),
        progress_panel(),
        uninstall_confirm_panel(),
        env_form_panel(),
        dev_form_panel(),
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
                    rx.el.div(
                        language_picker(AppStoreState),
                        rx.link(
                            rx.el.div(
                                rx.icon("activity", class_name="h-4 w-4"),
                                rx.el.span(AppStoreState.t["store_memory"]),
                                class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all",
                            ),
                            href="/monitor",
                        ),
                        rx.el.button(
                            rx.cond(
                                AppStoreState.loading,
                                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                                rx.icon("refresh-cw", class_name="h-4 w-4"),
                            ),
                            rx.el.span(AppStoreState.t["refresh"]),
                            on_click=AppStoreState.refresh,
                            disabled=AppStoreState.loading,
                            class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all disabled:opacity-50",
                        ),
                        class_name="flex flex-wrap items-center gap-2",
                    ),
                    class_name="flex flex-wrap items-center justify-between gap-3 mb-2",
                ),
                rx.el.p(
                    AppStoreState.t["store_subtitle"],
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
                        AppStoreState.t["store_empty"],
                        class_name="text-gray-400 font-medium",
                    ),
                    rx.el.p(
                        AppStoreState.t["store_empty_hint"],
                        class_name="text-gray-400 text-sm mt-1",
                    ),
                    class_name="flex flex-col items-center justify-center h-64 border-2 border-dashed border-gray-100 rounded-3xl",
                ),
            ),
            class_name="max-w-6xl mx-auto py-12 px-6",
        ),
        # The page's language, so CJK text is drawn with the right glyphs.
        lang=LocaleState.locale,
        class_name="min-h-screen bg-gray-50 font-['Inter']",
    )


app = rx.App(
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
app.add_page(
    monitor,
    route="/monitor",
    # The tab title is fixed when the app compiles, so it stays in the default
    # language; everything inside the page follows the picker.
    title="Container Memory",
    on_load=MonitorState.refresh,
)
