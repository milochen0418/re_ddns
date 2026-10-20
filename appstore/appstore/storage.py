"""Storage (``/storage``): the apps' shared data (Owned Collections) on this host.

Apps exchange data through collections (re_ddns ``docs/collections.md``):
each app writes its own items into ``by-app/<app>/`` and reads everyone's.
This page manages all of it the way a file manager manages files, but item
by item and within the rules collections keep:

  • Items   every item on this host and on the hosts it peers with, found by
            collection, kind, app, place and words.  Details show the manifest,
            the files and the lineage both ways (``derived_from`` and what was
            made from it), a preview, "Open with" (the installed apps whose
            intents accept the item's kind), fetching a copy from another host,
            and deleting.  Items are never renamed or edited: a ref must keep
            working for the apps that hold it.
  • Space   what each collection and each app's contribution takes, a quota
            per contribution, and data whose app is no longer installed.
  • Hosts   this node, its peers, and the copies fetched from them (the cap on
            copies, cleaning up).
  • Import  a person's own files become one item of the reserved owner
            ``_user``, which every app with access to the collection then sees.

Everything goes through the re-ddns node API with the admin token
(``admin.py``); the App Store never touches the files.  Previews come through
this app's backend (``thumb_endpoint``), so the browser never needs the token.

The page is translated like the others (``i18n``, ``lang.LocaleState``): every
text with ``{placeholders}`` is composed here in Python, and a language
switch reloads the page's data so the composed text follows.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import httpx
import reflex as rx
from starlette.requests import Request
from starlette.responses import Response

from .admin import admin_headers, admin_request_async
from .lang import LocaleState, language_picker

RE_DDNS_API_URL = os.environ.get("RE_DDNS_API_URL", "http://re-ddns:8000")
SERVICE_ZONE = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
CATALOG_PATH = os.environ.get("CATALOG_PATH", "/app/data/appstore_catalog.json")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")

PAGE_SIZE = 50
UPLOAD_ID = "storage_import"
USER_OWNER = "_user"
GENERIC_KIND = "file.generic"
NEW = "__new__"                  # select value: type a new collection / kind
GB = 1_000_000_000
_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
_KIND_ICONS = {"dicom": "scan", "video": "film", "audio": "music", "image": "image", "document": "file-text"}


def _api(path: str) -> str:
    return f"{RE_DDNS_API_URL}/api/collections{path}"


def _size(n: int | float) -> str:
    n = float(n or 0)
    for unit, step in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{int(n)} B"


def _date(iso: str) -> str:
    return (iso or "")[:16].replace("T", " ")


def _gb_text(n: int) -> str:
    return f"{n / GB:g}"


def _catalog_names() -> dict[str, str]:
    try:
        apps = json.loads(Path(CATALOG_PATH).read_text()).get("apps", [])
    except Exception:  # noqa: BLE001 - an unreadable catalog only costs names
        return {}
    return {str(a["subdomain"]): str(a.get("name") or a["subdomain"]) for a in apps if a.get("subdomain")}


def _installed() -> set[str] | None:
    """Subdomains with a ``smart-app-<sub>`` container (``None`` without the Docker socket)."""
    if not os.path.exists(DOCKER_SOCK):
        return None
    try:
        transport = httpx.HTTPTransport(uds=DOCKER_SOCK)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=5.0) as client:
            r = client.get("/containers/json", params={"all": "1", "filters": json.dumps({"name": ["smart-app-"]})})
        names = [n.lstrip("/") for c in r.json() for n in c.get("Names", [])]
    except Exception:  # noqa: BLE001
        return None
    return {n[len("smart-app-"):] for n in names if n.startswith("smart-app-")}


async def _call(method: str, path: str, *, timeout: float = 30.0, **kwargs) -> dict:
    """A node API call with the admin token; raises ``RuntimeError`` with the node's reason."""
    r = await admin_request_async(method, _api(path), timeout=timeout, **kwargs)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except ValueError:
            detail = r.text[:200]
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


async def _openers(kinds: set[str]) -> dict[str, list[dict]]:
    """``kind`` → the intent actions that open it (from the re-ddns intent registry)."""
    out: dict[str, list[dict]] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for kind in sorted(k for k in kinds if k):
            try:
                r = await client.get(f"{RE_DDNS_API_URL}/api/intent/openers", params={"kind": kind})
                out[kind] = r.json().get("openers", []) if r.status_code == 200 else []
            except (httpx.HTTPError, ValueError):
                out[kind] = []
    return out


def _open_url(opener: Mapping, ref: str) -> str:
    return f"https://{opener['app']}.{SERVICE_ZONE}{opener.get('route') or ''}?ref={quote(ref, safe='')}"


def _thumb_url(ref: str) -> str:
    return f"/api/storage/thumb?ref={quote(ref, safe='')}"


async def thumb_endpoint(request: Request) -> Response:
    """``GET /api/storage/thumb?ref=``: an item's preview, fetched from re-ddns with the admin token."""
    ref = request.query_params.get("ref", "")
    try:
        r = await admin_request_async("GET", _api("/_thumb"), params={"ref": ref}, timeout=15.0)
    except httpx.HTTPError:
        return Response(status_code=502)
    media = r.headers.get("content-type", "").split(";")[0].strip()
    if r.status_code != 200 or media not in _IMAGE_TYPES:
        return Response(status_code=404)
    return Response(r.content, media_type=media, headers={
        "Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"})


class StorageState(LocaleState):
    """The storage page.  Rows hold ready-made text, composed in the current language."""

    tab: str = "items"               # items | space | hosts
    loading: bool = False
    message: str = ""
    message_kind: str = "info"       # info | success | error
    show_langs: bool = False

    # ── items: filters, one page of rows, and the choices of the filters ──
    f_collection: str = ""
    f_kind: str = ""
    f_owner: str = ""
    f_location: str = "all"          # all | here | own | replica | remote
    f_sort: str = "newest"
    f_query: str = ""
    page: int = 0
    total: int = 0
    rows: list[dict[str, str]] = []
    collection_opts: list[dict[str, str]] = []
    kind_opts: list[dict[str, str]] = []
    owner_opts: list[dict[str, str]] = []
    range_text: str = ""

    # ── one item's details ──
    show_detail: bool = False
    detail: dict[str, str] = {}
    detail_files: list[dict[str, str]] = []
    detail_meta: list[dict[str, str]] = []
    detail_parents: list[dict[str, str]] = []
    detail_children: list[dict[str, str]] = []
    detail_openers: list[dict[str, str]] = []

    # ── a deletion waiting for confirmation ──
    confirm_what: str = ""           # item | contribution
    confirm_ref: str = ""
    confirm_collection: str = ""
    confirm_owner: str = ""
    confirm_title: str = ""
    confirm_body: str = ""
    confirm_warning: str = ""

    # ── a copy being fetched from another host ──
    fetching: str = ""
    fetch_text: str = ""

    # ── space ──
    disk_text: str = ""
    collections: list[dict[str, str]] = []
    contribs: list[dict[str, str]] = []
    quota_key: str = ""              # "<collection>|<owner>" being edited
    quota_value: str = ""

    # ── hosts ──
    node_name: str = ""
    node_open: bool = False
    peers: list[dict[str, str]] = []
    replica_text: str = ""
    cap_value: str = ""
    cap_is_set: bool = False

    # ── import ──
    show_import: bool = False
    imp_collection: str = ""
    imp_new_collection: str = ""
    imp_kind: str = GENERIC_KIND
    imp_new_kind: str = ""
    imp_title: str = ""
    imp_kinds: list[str] = [GENERIC_KIND]
    importing: bool = False
    import_text: str = ""

    _names: dict[str, str] = {}

    # ── helpers ─────────────────────────────────────────────────────────────

    def _say(self, text: str, kind: str = "info") -> None:
        self.message, self.message_kind = text, kind

    def _fmt(self, key: str, **args) -> str:
        return self._strings()[key].format(**args)

    def _owner_label(self, owner: str) -> str:
        if owner == USER_OWNER:
            return self._strings()["st_owner_user"]
        return self._names.get(owner, owner)

    def _where(self, row: Mapping) -> tuple[str, str]:
        if not row.get("local"):
            return "remote", self._fmt("st_on_host", host=row.get("home", ""))
        if row.get("replica"):
            return "copy", self._fmt("st_copy_from", host=row.get("home", ""))
        return "here", self._strings()["st_here"]

    # ── loading ─────────────────────────────────────────────────────────────

    async def _load_items(self, refresh: bool = False) -> None:
        params = {"location": self.f_location, "sort": self.f_sort, "limit": PAGE_SIZE,
                  "offset": self.page * PAGE_SIZE}
        for key, value in (("collection", self.f_collection), ("kind", self.f_kind),
                           ("owner", self.f_owner), ("q", self.f_query.strip())):
            if value:
                params[key] = value
        if refresh:
            params["refresh"] = "true"
        data = await _call("GET", "/_index", params=params)
        items = data.get("items", [])
        openers = await _openers({i.get("kind", "") for i in items})
        t = self._strings()
        rows = []
        for i in items:
            where_kind, where = self._where(i)
            first = (openers.get(i.get("kind", "")) or [None])[0]
            rows.append({
                "ref": i["ref"], "title": i.get("title") or i.get("id", ""), "kind": i.get("kind", ""),
                "collection": i.get("collection", ""),
                "icon": _KIND_ICONS.get(i.get("kind", "").split(".")[0], "file"),
                "owner": self._owner_label(i.get("owner", "")), "size": _size(i.get("bytes", 0)),
                "date": _date(i.get("created_at", "")), "where": where, "where_kind": where_kind,
                "files": self._fmt("st_files", count=i.get("files", 0)),
                "thumb": _thumb_url(i["ref"]) if i.get("preview") else "",
                "open_url": _open_url(first, i["ref"]) if first else "",
                "open_label": self._fmt("st_open_with", app=self._names.get(first["app"], first["app"])) if first else "",
                "can_fetch": "1" if where_kind == "remote" else "",
                "can_delete": "" if where_kind == "remote" else "1",
            })
        self.rows = rows
        self.total = int(data.get("total", 0))
        start = self.page * PAGE_SIZE
        self.range_text = (self._fmt("st_range", first=start + 1, last=start + len(rows), total=self.total)
                           if rows else "")
        facets = data.get("facets", {})

        def opts(name: str, all_key: str, label=lambda v: v) -> list[dict[str, str]]:
            return [{"value": "", "label": t[all_key]}] + [
                {"value": f["value"], "label": f"{label(f['value'])} ({f['items']})"} for f in facets.get(name, [])]

        self.collection_opts = opts("collections", "st_all_collections")
        self.kind_opts = opts("kinds", "st_all_kinds")
        self.owner_opts = opts("owners", "st_all_owners", self._owner_label)

    async def _load_space(self) -> None:
        data = await _call("GET", "/_usage")
        installed = await asyncio.to_thread(_installed)
        disk = data.get("disk") or {}
        self.disk_text = (self._fmt("st_disk", free=_size(disk.get("free", 0)), total=_size(disk.get("total", 0)),
                                    path=data.get("host_root", "")) if disk else "")
        collections, contribs = [], []
        for c in data.get("collections", []):
            collections.append({
                "name": c["name"],
                "summary": self._fmt("st_collection_summary", items=c.get("items", 0), size=_size(c.get("bytes", 0))),
                "copies": (self._fmt("st_collection_copies", items=c.get("replicas", 0),
                                     size=_size(c.get("replica_bytes", 0))) if c.get("replicas") else ""),
                "staging": (self._fmt("st_staging", size=_size(c.get("staging_bytes", 0)))
                            if c.get("staging_bytes") else ""),
            })
            for o in c.get("owners", []):
                owner = o["owner"]
                if owner == USER_OWNER:
                    status, status_kind = self._strings()["st_status_user"], "user"
                elif not o.get("items") and o.get("replicas"):
                    status, status_kind = self._strings()["st_status_copies"], "copies"
                elif installed is None or owner in installed:
                    status, status_kind = self._strings()["st_status_installed"], "installed"
                else:
                    status, status_kind = self._strings()["st_status_orphan"], "orphan"
                quota = int(o.get("quota") or 0)
                used = int(o.get("bytes") or 0)
                contribs.append({
                    "key": f"{c['name']}|{owner}", "collection": c["name"], "owner": owner,
                    "label": self._owner_label(owner), "status": status, "status_kind": status_kind,
                    "usage": self._fmt("st_contrib_usage", items=o.get("items", 0), size=_size(used)),
                    "copies": (self._fmt("st_collection_copies", items=o.get("replicas", 0),
                                         size=_size(o.get("replica_bytes", 0))) if o.get("replicas") else ""),
                    "quota": (self._fmt("st_quota_of", limit=_size(quota), percent=min(999, round(100 * used / quota)))
                              if quota else self._strings()["st_no_quota"]),
                    "over": "1" if quota and used > quota else "",
                    "quota_gb": _gb_text(quota) if quota else "",
                })
        self.collections, self.contribs = collections, contribs
        self.replica_text = self._fmt(
            "st_copies_total", size=_size(data.get("replica_bytes", 0)),
            cap=_size(data["replica_cap"]) if data.get("replica_cap") else self._strings()["st_no_cap"])
        self.node_name = str(data.get("node", ""))
        self.node_open = not data.get("node_token")

    async def _load_hosts(self) -> None:
        settings = await _call("GET", "/_settings")
        self.cap_is_set = bool(settings.get("replica_max_bytes_set"))
        cap = int(settings.get("replica_max_bytes") or 0)
        self.cap_value = _gb_text(cap) if cap else ""
        async with httpx.AsyncClient(timeout=10.0) as client:
            overview = (await client.get(_api(""))).json()
            env_peers = set((await client.get(_api("/_peers"))).json().get("from_env", []))
        t = self._strings()
        peers = []
        for name, p in sorted((overview.get("peers") or {}).items()):
            if not p.get("reachable"):
                state, kind = t["st_peer_down"], "down"
            elif not p.get("name_matches"):
                state, kind = self._fmt("st_peer_other_name", name=p.get("node", "")), "warn"
            else:
                state, kind = t["st_peer_ok"], "ok"
            peers.append({"name": name, "url": p.get("url", ""), "state": state, "kind": kind,
                          "env": "1" if name in env_peers else ""})
        self.peers = peers

    async def _reload(self, refresh: bool = False) -> None:
        self._names = await asyncio.to_thread(_catalog_names)
        try:
            await self._load_space()
            await self._load_items(refresh)
            # Peers are probed only when looked at: one that is down takes seconds to time out.
            if self.tab == "hosts":
                await self._load_hosts()
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_load_failed", error=exc), "error")

    # ── page events ─────────────────────────────────────────────────────────

    @rx.event
    async def load(self):
        """The page's on_load: everything, with the spinner."""
        self.loading = True
        yield
        await self._reload()
        self.loading = False

    @rx.event
    async def refresh(self):
        """The Refresh button: also re-reads every manifest on the node."""
        self.loading = True
        self.message = ""
        yield
        await self._reload(refresh=True)
        self.loading = False

    @rx.event
    async def set_tab(self, tab: str):
        self.tab = tab
        if tab == "hosts":
            try:
                await self._load_hosts()
            except Exception as exc:  # noqa: BLE001
                self._say(self._fmt("st_load_failed", error=exc), "error")

    @rx.event
    def toggle_langs(self):
        self.show_langs = not self.show_langs

    @rx.event
    def close_langs(self):
        self.show_langs = False

    @rx.event
    async def set_locale(self, code: str):
        """Switch language, and compose the page's text again in it."""
        self._set_locale(code)
        self.show_langs = False
        self.message = ""                # it was composed in the old language
        await self._reload()

    @rx.event
    def dismiss(self):
        self.message = ""

    # ── items: filters and pages ──

    async def _filtered(self):
        self.page = 0
        try:
            await self._load_items()
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_load_failed", error=exc), "error")

    @rx.event
    async def set_collection_filter(self, value: str):
        self.f_collection = value
        await self._filtered()

    @rx.event
    async def set_kind_filter(self, value: str):
        self.f_kind = value
        await self._filtered()

    @rx.event
    async def set_owner_filter(self, value: str):
        self.f_owner = value
        await self._filtered()

    @rx.event
    async def set_location_filter(self, value: str):
        self.f_location = value
        await self._filtered()

    @rx.event
    async def set_sort(self, value: str):
        self.f_sort = value
        await self._filtered()

    @rx.event
    async def search(self, form: dict):
        self.f_query = str(form.get("q", ""))
        await self._filtered()

    @rx.event
    async def clear_filters(self):
        self.f_collection = self.f_kind = self.f_owner = self.f_query = ""
        self.f_location, self.f_sort = "all", "newest"
        await self._filtered()

    @rx.event
    async def show_owner(self, collection: str, owner: str):
        """From the Space tab: list this contribution's items."""
        self.tab = "items"
        self.f_collection, self.f_owner, self.f_kind, self.f_query, self.f_location = collection, owner, "", "", "here"
        await self._filtered()

    @rx.event
    async def next_page(self):
        if (self.page + 1) * PAGE_SIZE < self.total:
            self.page += 1
            await self._load_items()

    @rx.event
    async def prev_page(self):
        if self.page > 0:
            self.page -= 1
            await self._load_items()

    # ── details ──

    @rx.event
    async def open_detail(self, ref: str):
        try:
            e = await _call("GET", "/_item", params={"ref": ref})
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_load_failed", error=exc), "error")
            return
        t = self._strings()
        manifest = e.get("manifest") if isinstance(e.get("manifest"), dict) else {}
        where_kind, where = self._where(e)
        self.detail = {
            "ref": e["ref"], "title": str(e.get("title") or e.get("id", "")), "kind": str(e.get("kind", "")),
            "owner": self._owner_label(str(e.get("owner", ""))), "where": where, "where_kind": where_kind,
            "size": _size(e.get("bytes", 0)), "created": _date(str(e.get("created_at", ""))),
            "source": str(manifest.get("source") or ""), "host_path": str(e.get("host_path") or ""),
            "thumb": _thumb_url(e["ref"]) if e.get("preview") else "",
            "files": self._fmt("st_files", count=len(manifest.get("files", []))),
            "can_fetch": "1" if where_kind == "remote" else "",
            "can_delete": "" if where_kind == "remote" else "1",
        }
        files = [f for f in manifest.get("files", []) if isinstance(f, dict)]
        self.detail_files = [{"path": str(f.get("path", "")), "size": _size(f.get("bytes", 0))} for f in files[:200]]
        if len(files) > 200:
            self.detail_files.append({"path": self._fmt("st_more_files", count=len(files) - 200), "size": ""})
        meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
        self.detail_meta = [{"key": str(k), "value": str(v)} for k, v in sorted(meta.items())]
        self.detail_parents = [
            {"ref": p["ref"], "label": p.get("title") or p["ref"], "here": "1" if p.get("here") else "",
             "note": "" if p.get("here") else t["st_not_here"]}
            for p in e.get("derived_from_items", [])
        ]
        self.detail_children = [
            {"ref": c["ref"], "label": c.get("title") or c["ref"], "note": self._owner_label(c.get("owner", ""))}
            for c in e.get("derived_into", [])
        ]
        openers = (await _openers({self.detail["kind"]})).get(self.detail["kind"], [])
        self.detail_openers = [
            {"url": _open_url(o, e["ref"]),
             "label": self._fmt("st_open_with", app=self._names.get(o["app"], o["app"])),
             "action": str(o.get("title") or o.get("action", ""))}
            for o in openers
        ]
        self.show_detail = True

    @rx.event
    def close_detail(self):
        self.show_detail = False

    # ── deleting ──

    @rx.event
    async def ask_delete_item(self, ref: str, title: str, size: str):
        t = self._strings()
        if self.show_detail and self.detail.get("ref") == ref:
            children = len(self.detail_children)
        else:
            try:
                children = len((await _call("GET", "/_item", params={"ref": ref})).get("derived_into", []))
            except Exception:  # noqa: BLE001 - the deletion itself will say what is wrong
                children = 0
        self.confirm_what, self.confirm_ref = "item", ref
        self.confirm_title = t["st_delete_item_title"]
        self.confirm_body = self._fmt("st_delete_item_body", title=title, size=size)
        self.confirm_warning = self._fmt("st_delete_lineage", count=children) if children else ""

    @rx.event
    def ask_delete_contribution(self, collection: str, owner: str):
        row = next((c for c in self.contribs if c["key"] == f"{collection}|{owner}"), None)
        if row is None:
            return
        self.confirm_what, self.confirm_collection, self.confirm_owner = "contribution", collection, owner
        self.confirm_title = self._strings()["st_delete_contrib_title"]
        self.confirm_body = self._fmt("st_delete_contrib_body", owner=row["label"], collection=collection,
                                      usage=row["usage"])
        self.confirm_warning = (self._strings()["st_delete_contrib_installed"]
                                if row["status_kind"] == "installed" else "")

    @rx.event
    def cancel_confirm(self):
        self.confirm_what = ""

    @rx.event
    async def confirm(self):
        what, self.confirm_what = self.confirm_what, ""
        try:
            if what == "item":
                c, _, rest = self.confirm_ref.partition(":")
                owner, _, item = rest.partition("/")
                await _call("DELETE", f"/{c}/by-app/{quote(owner)}/{quote(item)}")
                self.show_detail = False
                self._say(self._fmt("st_deleted", what=self.confirm_ref), "success")
            elif what == "contribution":
                await _call("DELETE", f"/_contributions/{quote(self.confirm_owner)}",
                            params={"collection": self.confirm_collection})
                self._say(self._fmt("st_deleted", what=f"{self.confirm_collection}/by-app/{self.confirm_owner}"),
                          "success")
            else:
                return
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_action_failed", error=exc), "error")
        await self._load_space()
        await self._load_items()

    # ── a copy from another host ──

    @rx.event(background=True)
    async def fetch_item(self, ref: str):
        collection = ref.split(":", 1)[0]
        async with self:
            if self.fetching:
                return
            self.fetching = ref
            self.fetch_text = self._strings()["st_fetch_start"]
        task = asyncio.create_task(
            admin_request_async("POST", _api(f"/{collection}/fetch"), json={"ref": ref}, timeout=3600.0))
        while not task.done():
            await asyncio.sleep(1.0)
            try:
                st = (await admin_request_async("GET", _api(f"/{collection}/fetch-status"),
                                                params={"ref": ref}, timeout=5.0)).json()
            except Exception:  # noqa: BLE001
                st = {}
            total = int(st.get("bytes_total") or 0)
            if total:
                async with self:
                    self.fetch_text = self._fmt("st_fetch_progress", done=_size(st.get("bytes_done", 0)),
                                                total=_size(total))
        try:
            r = task.result()
            ok = r.status_code == 200
            detail = "" if ok else r.text[:200]
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        async with self:
            self.fetching = ""
            if ok:
                self._say(self._fmt("st_fetched", ref=ref), "success")
                self.show_detail = False
            else:
                self._say(self._fmt("st_action_failed", error=detail), "error")
            try:
                await self._load_items()
                await self._load_space()
            except Exception:  # noqa: BLE001
                pass

    # ── quotas ──

    @rx.event
    def edit_quota(self, key: str):
        self.quota_key = key
        row = next((c for c in self.contribs if c["key"] == key), {})
        self.quota_value = row.get("quota_gb", "")

    @rx.event
    def set_quota_value(self, value: str):
        self.quota_value = value

    @rx.event
    def cancel_quota(self):
        self.quota_key = ""

    async def _put_quota(self, limit: int) -> None:
        collection, _, owner = self.quota_key.partition("|")
        try:
            await _call("PUT", "/_settings", json={"quota": {"collection": collection, "owner": owner, "bytes": limit}})
            self.quota_key = ""
            await self._load_space()
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_action_failed", error=exc), "error")

    @rx.event
    async def save_quota(self):
        try:
            limit = int(float(self.quota_value.strip() or "0") * GB)
        except ValueError:
            self._say(self._strings()["st_bad_number"], "error")
            return
        await self._put_quota(max(0, limit))

    @rx.event
    async def remove_quota(self):
        await self._put_quota(0)

    # ── hosts ──

    @rx.event
    def set_cap_value(self, value: str):
        self.cap_value = value

    async def _put_cap(self, value: int | None) -> None:
        try:
            res = await _call("PUT", "/_settings", json={"replica_max_bytes": value})
            if res.get("evicted"):
                self._say(self._fmt("st_evicted", count=len(res["evicted"])), "info")
            await self._load_hosts()
            await self._load_space()
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_action_failed", error=exc), "error")

    @rx.event
    async def save_cap(self):
        try:
            cap = int(float(self.cap_value.strip() or "0") * GB)
        except ValueError:
            self._say(self._strings()["st_bad_number"], "error")
            return
        await self._put_cap(max(0, cap))

    @rx.event
    async def reset_cap(self):
        await self._put_cap(None)

    @rx.event
    async def run_gc(self):
        try:
            res = await _call("POST", "/_gc", timeout=300.0)
            self._say(self._fmt("st_gc_done", removed=len(res.get("removed", [])) + len(res.get("evicted", [])),
                                staging=len(res.get("stale_staging", []))), "success")
            await self._load_space()
            await self._load_items()
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_action_failed", error=exc), "error")

    async def _put_peers(self, peers: dict[str, str]) -> None:
        try:
            await _call("PUT", "/_peers", json={"peers": peers})
            await self._load_hosts()
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_action_failed", error=exc), "error")

    @rx.event
    async def add_peer(self, form: dict):
        name, url = str(form.get("name", "")).strip(), str(form.get("url", "")).strip().rstrip("/")
        if not name or not url:
            return
        peers = {p["name"]: p["url"] for p in self.peers if not p["env"]}
        peers[name] = url
        await self._put_peers(peers)

    @rx.event
    async def remove_peer(self, name: str):
        await self._put_peers({p["name"]: p["url"] for p in self.peers if not p["env"] and p["name"] != name})

    # ── import ──

    @rx.event
    def open_import(self):
        names = [o["value"] for o in self.collection_opts if o["value"]]
        self.imp_collection = self.f_collection or (names[0] if names else NEW)
        self.imp_new_collection = self.imp_new_kind = self.imp_title = ""
        self.import_text = ""
        self._import_kinds()
        self.show_import = True

    def _import_kinds(self) -> None:
        kinds = sorted({o["value"] for o in self.kind_opts if o["value"]} | {GENERIC_KIND})
        self.imp_kinds = kinds
        self.imp_kind = GENERIC_KIND

    @rx.event
    def close_import(self):
        if not self.importing:
            self.show_import = False

    @rx.event
    def set_imp_collection(self, value: str):
        self.imp_collection = value

    @rx.event
    def set_imp_new_collection(self, value: str):
        self.imp_new_collection = value.strip().lower()

    @rx.event
    def set_imp_kind(self, value: str):
        self.imp_kind = value

    @rx.event
    def set_imp_new_kind(self, value: str):
        self.imp_new_kind = value.strip().lower()

    @rx.event
    def set_imp_title(self, value: str):
        self.imp_title = value

    @rx.event
    def import_progress(self, progress: dict):
        """Browser → App Store, while the files upload."""
        self.import_text = self._fmt("st_import_uploading", percent=int(float(progress.get("progress", 0)) * 100))

    @rx.event
    async def do_import(self, files: list[rx.UploadFile]):
        """Stream the uploaded files into a new ``_user`` item: begin, one PUT per file, finish."""
        collection = self.imp_new_collection if self.imp_collection == NEW else self.imp_collection
        kind = self.imp_new_kind if self.imp_kind == NEW else self.imp_kind
        if not files:
            self._say(self._strings()["st_import_nothing"], "error")
            return
        self.importing = True
        yield
        upload = ""
        try:
            began = await _call("POST", "/_import", json={"collection": collection, "kind": kind,
                                                         "title": self.imp_title.strip()})
            upload = began["upload"]
            headers = await asyncio.to_thread(admin_headers)
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=600.0, write=600.0)) as client:
                for n, f in enumerate(files, 1):
                    rel = _upload_path(f)
                    self.import_text = self._fmt("st_import_saving", n=n, total=len(files), name=rel)
                    yield

                    async def body(f=f):
                        while chunk := await f.read(1024 * 1024):
                            yield chunk

                    r = await client.put(_api(f"/_import/{upload}/files/{quote(rel)}"), content=body(),
                                         headers=headers)
                    if r.status_code != 200:
                        raise RuntimeError(f"{rel}: HTTP {r.status_code}: {r.text[:200]}")
            entry = await _call("POST", f"/_import/{upload}/finish", timeout=300.0)
            upload = ""
            self.show_import = False
            self._say(self._fmt("st_imported", title=entry.get("title", ""), ref=entry.get("ref", "")), "success")
            self.f_collection, self.f_owner, self.f_kind, self.f_query, self.f_location = (
                collection, USER_OWNER, "", "", "here")
            self.page = 0
            await self._load_items()
            await self._load_space()
            yield rx.clear_selected_files(UPLOAD_ID)
        except Exception as exc:  # noqa: BLE001
            self._say(self._fmt("st_action_failed", error=exc), "error")
        finally:
            if upload:
                try:
                    await _call("DELETE", f"/_import/{upload}")
                except Exception:  # noqa: BLE001
                    pass
            self.importing = False
            self.import_text = ""


def _upload_path(f: rx.UploadFile) -> str:
    """The file's path inside the item: kept from a dropped folder, else its name."""
    raw = str(f.path or f.name or "file").replace("\\", "/")
    parts = [p for p in raw.split("/") if p not in ("", ".", "..")]
    if parts and parts[0] == ".item":
        parts = parts[1:]
    return "/".join(parts) or "file"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_BTN = "flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all"
_SMALL = "flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold rounded-lg transition-all"
_SELECT = "px-3 py-2 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 max-w-[14rem]"
_FIELD = "px-3 py-2 bg-white border border-gray-200 rounded-xl text-sm text-gray-800"
_INPUT = f"{_FIELD} w-full"
_CARD = "bg-white rounded-2xl border border-gray-100 shadow-sm p-5"
_MODAL_BG = "fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 sm:p-6"


def _banner() -> rx.Component:
    return rx.cond(
        StorageState.message != "",
        rx.el.div(
            rx.icon(rx.match(StorageState.message_kind, ("success", "circle-check"), ("error", "circle-alert"), "info"),
                    class_name="h-5 w-5 mr-2 shrink-0"),
            rx.el.span(StorageState.message, class_name="font-medium flex-1 break-words min-w-0"),
            rx.el.button(rx.icon("x", class_name="h-4 w-4"), on_click=StorageState.dismiss,
                         class_name="ml-2 p-1 opacity-60 hover:opacity-100"),
            class_name=rx.match(
                StorageState.message_kind,
                ("success", "flex items-center p-4 bg-green-50 text-green-800 rounded-xl border border-green-100 mb-6"),
                ("error", "flex items-center p-4 bg-red-50 text-red-800 rounded-xl border border-red-100 mb-6"),
                "flex items-center p-4 bg-blue-50 text-blue-800 rounded-xl border border-blue-100 mb-6",
            ),
        ),
        None,
    )


def _tab(key: str, icon: str, label_key: str) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, class_name="h-4 w-4"),
        rx.el.span(StorageState.t[label_key]),
        on_click=StorageState.set_tab(key),
        class_name=rx.cond(
            StorageState.tab == key,
            "flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 text-white font-semibold",
            "flex items-center gap-2 px-4 py-2 rounded-xl text-gray-600 font-medium hover:bg-white",
        ),
    )


def _select(value, options, on_change) -> rx.Component:
    return rx.el.select(
        rx.foreach(options, lambda o: rx.el.option(o["label"], value=o["value"])),
        value=value, on_change=on_change, class_name=_SELECT,
    )


def _static_select(value, choices: list[tuple[str, str]], on_change) -> rx.Component:
    return rx.el.select(
        *[rx.el.option(StorageState.t[label_key], value=v) for v, label_key in choices],
        value=value, on_change=on_change, class_name=_SELECT,
    )


def _where_badge(kind, text) -> rx.Component:
    return rx.el.span(
        text,
        class_name=rx.match(
            kind,
            ("here", "px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-100"),
            ("copy", "px-2 py-0.5 rounded-full text-xs font-medium bg-violet-50 text-violet-700 border border-violet-100"),
            "px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-100",
        ),
    )


def _preview(thumb, icon, size: str) -> rx.Component:
    return rx.cond(
        thumb != "",
        rx.el.img(src=thumb, loading="lazy", alt="",
                  class_name=f"{size} rounded-xl object-cover bg-gray-100 border border-gray-100 shrink-0"),
        rx.el.div(rx.icon(icon, class_name="h-6 w-6 text-blue-600"),
                  class_name=f"{size} rounded-xl bg-blue-50 flex items-center justify-center shrink-0"),
    )


def _item_row(row: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        _preview(row["thumb"], row["icon"], "h-12 w-12"),
        rx.el.div(
            rx.el.button(row["title"], on_click=StorageState.open_detail(row["ref"]),
                         class_name="text-left font-semibold text-gray-900 hover:text-blue-700 truncate max-w-full"),
            rx.el.div(
                rx.el.span(row["kind"], class_name="font-mono text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600"),
                rx.el.span(row["owner"], class_name="text-xs text-gray-500"),
                rx.el.span(row["size"], class_name="text-xs text-gray-500"),
                rx.el.span(row["files"], class_name="text-xs text-gray-400"),
                rx.el.span(row["date"], class_name="text-xs text-gray-400"),
                _where_badge(row["where_kind"], row["where"]),
                class_name="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1",
            ),
            class_name="flex-1 min-w-0",
        ),
        rx.el.div(
            rx.cond(
                row["open_url"] != "",
                rx.el.a(rx.icon("external-link", class_name="h-3.5 w-3.5"), rx.el.span(row["open_label"]),
                        href=row["open_url"], target="_blank", rel="noopener",
                        class_name=f"{_SMALL} bg-blue-50 text-blue-700 hover:bg-blue-100"),
                None,
            ),
            rx.cond(
                row["can_fetch"] == "1",
                rx.el.button(rx.icon("cloud-download", class_name="h-3.5 w-3.5"),
                             rx.el.span(StorageState.t["st_fetch_here"]),
                             on_click=StorageState.fetch_item(row["ref"]), disabled=StorageState.fetching != "",
                             class_name=f"{_SMALL} bg-amber-50 text-amber-700 hover:bg-amber-100 disabled:opacity-50"),
                None,
            ),
            rx.el.button(rx.icon("info", class_name="h-3.5 w-3.5"), rx.el.span(StorageState.t["st_details"]),
                         on_click=StorageState.open_detail(row["ref"]),
                         class_name=f"{_SMALL} bg-gray-100 text-gray-700 hover:bg-gray-200"),
            rx.cond(
                row["can_delete"] == "1",
                rx.el.button(rx.icon("trash-2", class_name="h-3.5 w-3.5"),
                             on_click=StorageState.ask_delete_item(row["ref"], row["title"], row["size"]),
                             title=StorageState.t["st_delete"],
                             class_name=f"{_SMALL} bg-red-50 text-red-600 hover:bg-red-100"),
                None,
            ),
            class_name="flex flex-wrap items-center justify-end gap-1.5 sm:ml-auto",
        ),
        class_name="flex flex-col sm:flex-row sm:items-center gap-3 p-3 bg-white rounded-2xl border border-gray-100 hover:border-blue-100",
    )


def _items_tab() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.form(
                rx.el.div(
                    rx.icon("search", class_name="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2"),
                    rx.el.input(name="q", default_value=StorageState.f_query, key=StorageState.f_query,
                                placeholder=StorageState.t["st_search"], class_name=f"{_INPUT} pl-9"),
                    class_name="relative flex-1 min-w-[12rem]",
                ),
                on_submit=StorageState.search,
                class_name="flex flex-1 min-w-[12rem]",
            ),
            rx.el.button(rx.icon("upload", class_name="h-4 w-4"), rx.el.span(StorageState.t["st_import"]),
                         on_click=StorageState.open_import,
                         class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700"),
            class_name="flex flex-wrap items-center gap-2 mb-3",
        ),
        rx.el.div(
            _select(StorageState.f_collection, StorageState.collection_opts, StorageState.set_collection_filter),
            _select(StorageState.f_kind, StorageState.kind_opts, StorageState.set_kind_filter),
            _select(StorageState.f_owner, StorageState.owner_opts, StorageState.set_owner_filter),
            _static_select(StorageState.f_location, [
                ("all", "st_loc_all"), ("here", "st_loc_here"), ("own", "st_loc_own"),
                ("replica", "st_loc_replica"), ("remote", "st_loc_remote")], StorageState.set_location_filter),
            _static_select(StorageState.f_sort, [
                ("newest", "st_sort_newest"), ("oldest", "st_sort_oldest"), ("largest", "st_sort_largest"),
                ("smallest", "st_sort_smallest"), ("title", "st_sort_title")], StorageState.set_sort),
            rx.el.button(StorageState.t["st_clear"], on_click=StorageState.clear_filters,
                         class_name="px-3 py-2 text-sm text-gray-500 hover:text-gray-800"),
            class_name="flex flex-wrap items-center gap-2 mb-4",
        ),
        rx.cond(
            StorageState.fetching != "",
            rx.el.div(rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"), rx.el.span(StorageState.fetch_text),
                      class_name="flex items-center gap-2 p-3 mb-3 bg-amber-50 text-amber-800 rounded-xl text-sm border border-amber-100"),
            None,
        ),
        rx.cond(
            StorageState.rows.length() > 0,
            rx.el.div(rx.foreach(StorageState.rows, _item_row), class_name="flex flex-col gap-2"),
            rx.el.div(
                rx.icon("package-open", class_name="h-12 w-12 text-gray-300 mb-4"),
                rx.el.p(StorageState.t["st_no_items"], class_name="text-gray-400 font-medium"),
                rx.el.p(StorageState.t["st_no_items_hint"], class_name="text-gray-400 text-sm mt-1 text-center max-w-md"),
                class_name="flex flex-col items-center justify-center h-64 border-2 border-dashed border-gray-100 rounded-3xl px-6",
            ),
        ),
        rx.el.div(
            rx.el.span(StorageState.range_text, class_name="text-sm text-gray-500"),
            rx.el.div(
                rx.el.button(rx.icon("chevron-left", class_name="h-4 w-4"), on_click=StorageState.prev_page,
                             disabled=StorageState.page == 0, class_name=f"{_BTN} disabled:opacity-40"),
                rx.el.button(rx.icon("chevron-right", class_name="h-4 w-4"), on_click=StorageState.next_page,
                             disabled=(StorageState.page + 1) * PAGE_SIZE >= StorageState.total,
                             class_name=f"{_BTN} disabled:opacity-40"),
                class_name="flex gap-2",
            ),
            class_name="flex items-center justify-between mt-4",
        ),
    )


def _status_badge(kind, text) -> rx.Component:
    return rx.el.span(
        text,
        class_name=rx.match(
            kind,
            ("installed", "px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-100"),
            ("orphan", "px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200"),
            ("user", "px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100"),
            "px-2 py-0.5 rounded-full text-xs font-medium bg-violet-50 text-violet-700 border border-violet-100",
        ),
    )


def _contrib_row(row: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(row["label"], class_name="font-semibold text-gray-900"),
                _status_badge(row["status_kind"], row["status"]),
                class_name="flex flex-wrap items-center gap-2",
            ),
            rx.el.div(
                rx.el.span(row["usage"]),
                rx.cond(row["copies"] != "", rx.el.span(row["copies"], class_name="text-violet-700"), None),
                rx.el.span(row["quota"], class_name=rx.cond(row["over"] == "1", "text-red-600 font-semibold", "")),
                class_name="flex flex-wrap gap-x-3 text-xs text-gray-500 mt-1",
            ),
            class_name="flex-1 min-w-0",
        ),
        rx.cond(
            StorageState.quota_key == row["key"],
            rx.el.div(
                rx.el.input(value=StorageState.quota_value, on_change=StorageState.set_quota_value,
                            placeholder="GB", input_mode="decimal", class_name=f"{_FIELD} w-24"),
                rx.el.span("GB", class_name="text-xs text-gray-500"),
                rx.el.button(StorageState.t["st_save"], on_click=StorageState.save_quota,
                             class_name=f"{_SMALL} bg-blue-600 text-white hover:bg-blue-700"),
                rx.el.button(StorageState.t["st_no_limit"], on_click=StorageState.remove_quota,
                             class_name=f"{_SMALL} bg-gray-100 text-gray-700 hover:bg-gray-200"),
                rx.el.button(rx.icon("x", class_name="h-3.5 w-3.5"), on_click=StorageState.cancel_quota,
                             class_name=f"{_SMALL} text-gray-500"),
                class_name="flex items-center gap-1.5",
            ),
            rx.el.div(
                rx.el.button(rx.icon("list", class_name="h-3.5 w-3.5"), rx.el.span(StorageState.t["st_show_items"]),
                             on_click=StorageState.show_owner(row["collection"], row["owner"]),
                             class_name=f"{_SMALL} bg-gray-100 text-gray-700 hover:bg-gray-200"),
                rx.el.button(rx.icon("gauge", class_name="h-3.5 w-3.5"), rx.el.span(StorageState.t["st_set_quota"]),
                             on_click=StorageState.edit_quota(row["key"]),
                             class_name=f"{_SMALL} bg-gray-100 text-gray-700 hover:bg-gray-200"),
                rx.el.button(rx.icon("trash-2", class_name="h-3.5 w-3.5"), rx.el.span(StorageState.t["st_delete_data"]),
                             on_click=StorageState.ask_delete_contribution(row["collection"], row["owner"]),
                             class_name=f"{_SMALL} bg-red-50 text-red-600 hover:bg-red-100"),
                class_name="flex flex-wrap items-center gap-1.5",
            ),
        ),
        class_name="flex flex-col md:flex-row md:items-center gap-3 py-3 border-t border-gray-100 first:border-t-0",
    )


def _collection_card(c: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon("database", class_name="h-5 w-5 text-blue-600"),
            rx.el.h3(c["name"], class_name="text-lg font-bold text-gray-900 font-mono"),
            rx.el.span(c["summary"], class_name="text-sm text-gray-500"),
            rx.cond(c["copies"] != "", rx.el.span(c["copies"], class_name="text-sm text-violet-700"), None),
            rx.cond(c["staging"] != "", rx.el.span(c["staging"], class_name="text-sm text-amber-700"), None),
            class_name="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2",
        ),
        rx.el.div(
            rx.foreach(StorageState.contribs, lambda row: rx.cond(row["collection"] == c["name"], _contrib_row(row), None)),
        ),
        class_name=_CARD,
    )


def _space_tab() -> rx.Component:
    return rx.el.div(
        rx.cond(StorageState.disk_text != "",
                rx.el.p(rx.icon("hard-drive", class_name="h-4 w-4 inline mr-2"), StorageState.disk_text,
                        class_name="text-sm text-gray-600 mb-4"),
                None),
        rx.el.p(StorageState.t["st_space_hint"], class_name="text-sm text-gray-500 mb-4"),
        rx.cond(
            StorageState.collections.length() > 0,
            rx.el.div(rx.foreach(StorageState.collections, _collection_card), class_name="flex flex-col gap-4"),
            rx.el.p(StorageState.t["st_no_collections"], class_name="text-gray-400 p-6 text-center"),
        ),
    )


def _peer_row(p: rx.Var[dict]) -> rx.Component:
    return rx.el.div(
        rx.icon(rx.match(p["kind"], ("ok", "circle-check"), ("warn", "triangle-alert"), "circle-x"),
                class_name=rx.match(p["kind"], ("ok", "h-4 w-4 text-green-600"), ("warn", "h-4 w-4 text-amber-600"),
                                    "h-4 w-4 text-red-500")),
        rx.el.span(p["name"], class_name="font-semibold text-gray-900 font-mono"),
        rx.el.span(p["url"], class_name="text-sm text-gray-500 font-mono truncate"),
        rx.el.span(p["state"], class_name="text-xs text-gray-500"),
        rx.cond(
            p["env"] == "1",
            rx.el.span(StorageState.t["st_peer_env"], class_name="ml-auto text-xs text-gray-400"),
            rx.el.button(rx.icon("x", class_name="h-3.5 w-3.5"), on_click=StorageState.remove_peer(p["name"]),
                         title=StorageState.t["st_remove"], class_name=f"ml-auto {_SMALL} text-gray-500 hover:bg-gray-100"),
        ),
        class_name="flex flex-wrap items-center gap-2 py-2 border-t border-gray-100 first:border-t-0",
    )


def _hosts_tab() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(rx.icon("server", class_name="h-5 w-5 text-blue-600"),
                      rx.el.h3(StorageState.t["st_this_host"], class_name="text-lg font-bold text-gray-900"),
                      rx.el.span(StorageState.node_name, class_name="font-mono text-sm text-gray-600"),
                      class_name="flex items-center gap-3 mb-2"),
            rx.cond(StorageState.node_open,
                    rx.el.p(rx.icon("triangle-alert", class_name="h-4 w-4 inline mr-1"), StorageState.t["st_node_open"],
                            class_name="text-sm p-3 bg-amber-50 text-amber-800 rounded-xl border border-amber-100"),
                    None),
            class_name=_CARD,
        ),
        rx.el.div(
            rx.el.h3(StorageState.t["st_peers"], class_name="text-lg font-bold text-gray-900 mb-1"),
            rx.el.p(StorageState.t["st_peers_hint"], class_name="text-sm text-gray-500 mb-3"),
            rx.cond(StorageState.peers.length() > 0,
                    rx.el.div(rx.foreach(StorageState.peers, _peer_row), class_name="mb-3"),
                    rx.el.p(StorageState.t["st_no_peers"], class_name="text-sm text-gray-400 mb-3")),
            rx.el.form(
                rx.el.input(name="name", placeholder=StorageState.t["st_peer_name"], class_name=f"{_INPUT} sm:w-40"),
                rx.el.input(name="url", placeholder="http://192.168.1.20", class_name=f"{_INPUT} sm:flex-1"),
                rx.el.button(rx.icon("plus", class_name="h-4 w-4"), rx.el.span(StorageState.t["st_add_peer"]),
                             type="submit", class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 shrink-0"),
                on_submit=StorageState.add_peer, reset_on_submit=True,
                class_name="flex flex-col sm:flex-row gap-2",
            ),
            class_name=_CARD,
        ),
        rx.el.div(
            rx.el.h3(StorageState.t["st_copies"], class_name="text-lg font-bold text-gray-900 mb-1"),
            rx.el.p(StorageState.replica_text, class_name="text-sm text-gray-600 mb-1"),
            rx.el.p(StorageState.t["st_copies_hint"], class_name="text-sm text-gray-500 mb-3"),
            rx.el.div(
                rx.el.span(StorageState.t["st_cap"], class_name="text-sm text-gray-700"),
                rx.el.input(value=StorageState.cap_value, on_change=StorageState.set_cap_value, input_mode="decimal",
                            placeholder=StorageState.t["st_no_cap"], class_name=f"{_FIELD} w-32"),
                rx.el.span("GB", class_name="text-sm text-gray-500"),
                rx.el.button(StorageState.t["st_save"], on_click=StorageState.save_cap,
                             class_name=f"{_SMALL} bg-blue-600 text-white hover:bg-blue-700"),
                rx.cond(StorageState.cap_is_set,
                        rx.el.button(StorageState.t["st_cap_default"], on_click=StorageState.reset_cap,
                                     class_name=f"{_SMALL} bg-gray-100 text-gray-700 hover:bg-gray-200"),
                        None),
                rx.el.button(rx.icon("brush-cleaning", class_name="h-3.5 w-3.5"), rx.el.span(StorageState.t["st_gc"]),
                             on_click=StorageState.run_gc,
                             class_name=f"{_SMALL} bg-gray-100 text-gray-700 hover:bg-gray-200 sm:ml-auto"),
                class_name="flex flex-wrap items-center gap-2",
            ),
            class_name=_CARD,
        ),
        class_name="flex flex-col gap-4",
    )


def _link_list(rows, empty_key: str) -> rx.Component:
    return rx.cond(
        rows.length() > 0,
        rx.el.div(rx.foreach(rows, lambda r: rx.el.div(
            rx.el.button(r["label"], on_click=StorageState.open_detail(r["ref"]),
                         class_name="text-left text-sm text-blue-700 hover:underline truncate"),
            rx.el.span(r["note"], class_name="text-xs text-gray-400 shrink-0"),
            class_name="flex items-center gap-2")), class_name="flex flex-col gap-1"),
        rx.el.p(StorageState.t[empty_key], class_name="text-sm text-gray-400"),
    )


def _section(title_key: str, *children) -> rx.Component:
    return rx.el.div(
        rx.el.h4(StorageState.t[title_key], class_name="text-xs font-bold uppercase tracking-wide text-gray-400 mb-1.5"),
        *children,
        class_name="mb-4",
    )


def _detail_panel() -> rx.Component:
    d = StorageState.detail
    return rx.cond(
        StorageState.show_detail,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    _preview(d["thumb"], "file", "h-20 w-20"),
                    rx.el.div(
                        rx.el.h3(d["title"], class_name="text-lg font-bold text-gray-900 break-words"),
                        rx.el.div(
                            rx.el.span(d["kind"], class_name="font-mono text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600"),
                            rx.el.span(d["owner"], class_name="text-xs text-gray-500"),
                            _where_badge(d["where_kind"], d["where"]),
                            class_name="flex flex-wrap items-center gap-2 mt-1",
                        ),
                        rx.el.code(d["ref"], class_name="block mt-2 text-xs font-mono text-gray-500 break-all select-all"),
                        class_name="flex-1 min-w-0",
                    ),
                    rx.el.button(rx.icon("x", class_name="h-5 w-5"), on_click=StorageState.close_detail,
                                 class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg self-start"),
                    class_name="flex gap-4 mb-4",
                ),
                rx.el.div(
                    rx.foreach(StorageState.detail_openers, lambda o: rx.el.a(
                        rx.icon("external-link", class_name="h-4 w-4"), rx.el.span(o["label"]),
                        href=o["url"], target="_blank", rel="noopener", title=o["action"],
                        class_name="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700")),
                    rx.cond(d["can_fetch"] == "1",
                            rx.el.button(rx.icon("cloud-download", class_name="h-4 w-4"),
                                         rx.el.span(StorageState.t["st_fetch_here"]),
                                         on_click=StorageState.fetch_item(d["ref"]), disabled=StorageState.fetching != "",
                                         class_name="flex items-center gap-2 px-3 py-2 bg-amber-50 text-amber-800 text-sm font-semibold rounded-xl hover:bg-amber-100 disabled:opacity-50"),
                            None),
                    rx.cond(d["can_delete"] == "1",
                            rx.el.button(rx.icon("trash-2", class_name="h-4 w-4"), rx.el.span(StorageState.t["st_delete"]),
                                         on_click=StorageState.ask_delete_item(d["ref"], d["title"], d["size"]),
                                         class_name="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-600 text-sm font-semibold rounded-xl hover:bg-red-100 ml-auto"),
                            None),
                    class_name="flex flex-wrap items-center gap-2 mb-4",
                ),
                rx.cond(StorageState.detail_openers.length() == 0,
                        rx.el.p(StorageState.t["st_no_openers"], class_name="text-xs text-gray-400 -mt-2 mb-4"), None),
                rx.el.div(
                    rx.el.div(rx.el.span(StorageState.t["st_size"], class_name="text-gray-400"), rx.el.span(d["size"]),
                              rx.el.span(d["files"], class_name="text-gray-400"), class_name="flex gap-2"),
                    rx.el.div(rx.el.span(StorageState.t["st_created"], class_name="text-gray-400"), rx.el.span(d["created"]),
                              class_name="flex gap-2"),
                    rx.cond(d["source"] != "",
                            rx.el.div(rx.el.span(StorageState.t["st_source"], class_name="text-gray-400 shrink-0"),
                                      rx.el.span(d["source"], class_name="break-all"), class_name="flex gap-2"), None),
                    rx.cond(d["host_path"] != "",
                            rx.el.div(rx.el.span(StorageState.t["st_on_disk"], class_name="text-gray-400 shrink-0"),
                                      rx.el.code(d["host_path"], class_name="font-mono text-xs break-all select-all"),
                                      class_name="flex gap-2"), None),
                    class_name="flex flex-col gap-1 text-sm text-gray-700 mb-4",
                ),
                rx.cond(StorageState.detail_meta.length() > 0,
                        _section("st_meta", rx.el.div(rx.foreach(StorageState.detail_meta, lambda m: rx.el.div(
                            rx.el.span(m["key"], class_name="text-gray-400 font-mono text-xs shrink-0"),
                            rx.el.span(m["value"], class_name="text-sm text-gray-700 break-words min-w-0"),
                            class_name="flex gap-3")), class_name="flex flex-col gap-1")),
                        None),
                _section("st_made_from", _link_list(StorageState.detail_parents, "st_none")),
                _section("st_made_into", _link_list(StorageState.detail_children, "st_none")),
                _section("st_files_title", rx.el.div(rx.foreach(StorageState.detail_files, lambda f: rx.el.div(
                    rx.el.span(f["path"], class_name="font-mono text-xs text-gray-700 truncate"),
                    rx.el.span(f["size"], class_name="text-xs text-gray-400 shrink-0 ml-auto"),
                    class_name="flex gap-3")), class_name="flex flex-col gap-0.5 max-h-48 overflow-y-auto pr-1")),
                class_name="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name=_MODAL_BG,
        ),
        None,
    )


def _confirm_panel() -> rx.Component:
    return rx.cond(
        StorageState.confirm_what != "",
        rx.el.div(
            rx.el.div(
                rx.el.div(rx.icon("trash-2", class_name="h-6 w-6 text-red-600"),
                          rx.el.h3(StorageState.confirm_title, class_name="text-lg font-bold text-gray-900"),
                          class_name="flex items-center gap-3 mb-2"),
                rx.el.p(StorageState.confirm_body, class_name="text-sm text-gray-600 mb-3 leading-relaxed break-words"),
                rx.cond(StorageState.confirm_warning != "",
                        rx.el.p(StorageState.confirm_warning,
                                class_name="p-3 mb-3 bg-amber-50 text-amber-800 rounded-xl text-sm border border-amber-100"),
                        None),
                rx.el.div(
                    rx.el.button(StorageState.t["cancel"], on_click=StorageState.cancel_confirm,
                                 class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200"),
                    rx.el.button(rx.icon("trash-2", class_name="h-4 w-4"), rx.el.span(StorageState.t["st_delete"]),
                                 on_click=StorageState.confirm,
                                 class_name="flex items-center gap-2 px-4 py-2 bg-red-600 text-white font-semibold rounded-xl hover:bg-red-700"),
                    class_name="flex justify-end gap-2",
                ),
                class_name="w-full max-w-lg bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name=f"{_MODAL_BG} z-[60]",
        ),
        None,
    )


def _import_panel() -> rx.Component:
    return rx.cond(
        StorageState.show_import,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(rx.icon("upload", class_name="h-6 w-6 text-blue-600"),
                              rx.el.h3(StorageState.t["st_import_title"], class_name="text-lg font-bold text-gray-900"),
                              class_name="flex items-center gap-3"),
                    rx.el.button(rx.icon("x", class_name="h-5 w-5"), on_click=StorageState.close_import,
                                 disabled=StorageState.importing, class_name="p-1 text-gray-400 hover:text-gray-700 rounded-lg"),
                    class_name="flex items-center justify-between mb-2",
                ),
                rx.el.p(StorageState.t["st_import_hint"], class_name="text-sm text-gray-500 mb-4"),
                rx.el.label(StorageState.t["st_collection"], class_name="block text-sm font-semibold text-gray-700 mb-1"),
                rx.el.select(
                    rx.foreach(StorageState.collection_opts, lambda o: rx.cond(
                        o["value"] != "", rx.el.option(o["value"], value=o["value"]), None)),
                    rx.el.option(StorageState.t["st_new_collection"], value=NEW),
                    value=StorageState.imp_collection, on_change=StorageState.set_imp_collection,
                    class_name=f"{_SELECT} max-w-none w-full mb-2",
                ),
                rx.cond(StorageState.imp_collection == NEW,
                        rx.el.input(value=StorageState.imp_new_collection, on_change=StorageState.set_imp_new_collection,
                                    placeholder="documents", class_name=f"{_INPUT} mb-2 font-mono"),
                        None),
                rx.el.label(StorageState.t["st_kind"], class_name="block text-sm font-semibold text-gray-700 mb-1 mt-2"),
                rx.el.select(
                    rx.foreach(StorageState.imp_kinds, lambda k: rx.el.option(k, value=k)),
                    rx.el.option(StorageState.t["st_other_kind"], value=NEW),
                    value=StorageState.imp_kind, on_change=StorageState.set_imp_kind,
                    class_name=f"{_SELECT} max-w-none w-full mb-2 font-mono",
                ),
                rx.cond(StorageState.imp_kind == NEW,
                        rx.el.input(value=StorageState.imp_new_kind, on_change=StorageState.set_imp_new_kind,
                                    placeholder="document.pdf", class_name=f"{_INPUT} mb-2 font-mono"),
                        None),
                rx.el.p(StorageState.t["st_kind_hint"], class_name="text-xs text-gray-400 mb-2"),
                rx.el.label(StorageState.t["st_title"], class_name="block text-sm font-semibold text-gray-700 mb-1 mt-2"),
                rx.el.input(value=StorageState.imp_title, on_change=StorageState.set_imp_title,
                            placeholder=StorageState.t["st_title_placeholder"], class_name=f"{_INPUT} mb-3"),
                rx.upload(
                    rx.el.div(
                        rx.icon("folder-open", class_name="h-8 w-8 text-blue-500 mb-2"),
                        rx.el.p(StorageState.t["st_drop"], class_name="text-sm text-gray-600 text-center"),
                        class_name="flex flex-col items-center justify-center p-6",
                    ),
                    id=UPLOAD_ID, multiple=True,
                    class_name="border-2 border-dashed border-blue-200 rounded-2xl bg-blue-50/40 cursor-pointer hover:bg-blue-50",
                ),
                rx.el.div(
                    rx.foreach(rx.selected_files(UPLOAD_ID), lambda name: rx.el.span(
                        name, class_name="text-xs font-mono text-gray-600 px-2 py-0.5 bg-gray-100 rounded")),
                    class_name="flex flex-wrap gap-1 mt-2 max-h-24 overflow-y-auto",
                ),
                rx.cond(StorageState.import_text != "",
                        rx.el.p(rx.icon("loader-circle", class_name="h-4 w-4 inline mr-2 animate-spin"),
                                StorageState.import_text, class_name="text-sm text-blue-700 mt-3"),
                        None),
                rx.el.div(
                    rx.el.button(StorageState.t["cancel"],
                                 on_click=[rx.clear_selected_files(UPLOAD_ID), StorageState.close_import],
                                 disabled=StorageState.importing,
                                 class_name="px-4 py-2 bg-gray-100 text-gray-600 font-semibold rounded-xl hover:bg-gray-200 disabled:opacity-50"),
                    rx.el.button(
                        rx.cond(StorageState.importing, rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                                rx.icon("upload", class_name="h-4 w-4")),
                        rx.el.span(StorageState.t["st_import_go"]),
                        # The selection is cleared by do_import once the item is published.
                        on_click=StorageState.do_import(rx.upload_files(
                            upload_id=UPLOAD_ID, on_upload_progress=StorageState.import_progress)),
                        disabled=StorageState.importing,
                        class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 disabled:opacity-50",
                    ),
                    class_name="flex justify-end gap-2 mt-4",
                ),
                class_name="w-full max-w-lg max-h-[90vh] overflow-y-auto bg-white rounded-3xl border border-gray-100 shadow-2xl p-6",
            ),
            class_name=_MODAL_BG,
        ),
        None,
    )


def storage() -> rx.Component:
    return rx.el.main(
        rx.cond(StorageState.show_langs,
                rx.el.div(on_click=StorageState.close_langs, class_name="fixed inset-0 z-10"), None),
        _detail_panel(),
        _confirm_panel(),
        _import_panel(),
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.icon("hard-drive", class_name="h-8 w-8 text-blue-600"),
                        rx.el.h1(StorageState.t["st_page_title"], class_name="text-3xl font-black text-gray-900"),
                        class_name="flex items-center gap-3",
                    ),
                    rx.el.div(
                        language_picker(StorageState),
                        rx.el.button(
                            rx.cond(StorageState.loading, rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                                    rx.icon("refresh-cw", class_name="h-4 w-4")),
                            rx.el.span(StorageState.t["refresh"]),
                            on_click=StorageState.refresh, disabled=StorageState.loading,
                            class_name=f"{_BTN} disabled:opacity-50",
                        ),
                        rx.link(rx.el.div(rx.icon("arrow-left", class_name="h-4 w-4"),
                                          rx.el.span(StorageState.t["back_to_store"]), class_name=_BTN), href="/"),
                        class_name="flex flex-wrap items-center gap-2",
                    ),
                    class_name="flex flex-wrap items-center justify-between gap-3 mb-2",
                ),
                rx.el.p(StorageState.t["st_subtitle"], class_name="text-gray-500"),
                class_name="mb-6",
            ),
            _banner(),
            rx.el.div(
                _tab("items", "layers", "st_tab_items"),
                _tab("space", "chart-pie", "st_tab_space"),
                _tab("hosts", "network", "st_tab_hosts"),
                class_name="flex flex-wrap gap-1 p-1 bg-gray-100 rounded-2xl w-fit mb-6",
            ),
            rx.match(StorageState.tab, ("space", _space_tab()), ("hosts", _hosts_tab()), _items_tab()),
            class_name="max-w-6xl mx-auto py-12 px-4 sm:px-6",
        ),
        lang=LocaleState.locale,
        class_name="min-h-screen bg-gray-50 font-['Inter']",
    )
