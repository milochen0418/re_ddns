"""Owned Collections node: shared storage between apps, on one host and across hosts.

A *collection* (``dicom``, ``video``, ...) is one directory tree that every
app with access sees at ``/data/collections/<collection>`` (read-only) plus
its own writable *contribution* ``by-app/<app>/``.  An *item* is a directory
of payload files plus a hidden ``.item/`` directory holding its bookkeeping
(``manifest.json``, ``replica.json``); the manifest is written last, so an
item is either complete or invisible, and an app that treats the directory
as a plain folder of files never sees the bookkeeping.  Apps use ``reflex_ddns_auth.collections``; this
module is the platform side:

    mounts      ``storage_binds()`` turns a catalog ``storage`` declaration into
                the two bind mounts and the env vars of an app container.
    index       ``GET /api/collections/<c>/items`` lists local items and, through
                the peers, items that live on other hosts.
    transfer    ``POST /api/collections/<c>/fetch {ref}`` copies an item from its
                home host into the local tree (a *replica*, marked ``.item/replica.json``);
                the home host serves it with the ``manifest.json`` / ``files/``
                endpoints.  Writes never cross hosts: every app writes on its own
                host, readers pull once and then read from local disk.
    lifecycle   contributions per app for uninstall, replica garbage collection.
    manage      what the App Store's storage page uses (admin token, see
                ``admin_auth``): usage and quotas, a searchable index of every item
                (``collections_index``), item details with lineage, previews,
                deleting an item, the replica cap, and importing a user's own files
                as items of the reserved owner ``_user``.

Configuration (environment):

    COLLECTIONS_ROOT             where this container sees the tree (default /collections)
    COLLECTIONS_HOST_ROOT        the same directory on the Docker host, used for binds
    RE_DDNS_NODE_NAME            this host's name in refs' ``home`` (default: hostname)
    RE_DDNS_PEERS                "name=url,name=url" of other re-ddns nodes; the file
                                 ``<data>/collections_peers.json`` {"peers": {...}} is merged in
    RE_DDNS_NODE_TOKEN           shared secret peers must present (header X-Re-DDNS-Node-Token)
    RE_DDNS_PEER_HOST_HEADER     Host header sent to peers (default home.<zone>, so a peer's
                                 nginx routes the request to its re-ddns backend)
    COLLECTIONS_REPLICA_MAX_BYTES  cap on replica bytes per host; 0 = unlimited.  The storage
                                 page can override it (``<data>/collections_settings.json``,
                                 which also holds the quotas)
    HOST_UID / HOST_GID          owner for directories this node creates (Linux hosts)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from re_ddns.api.admin_auth import require_admin
from re_ddns.api.collections_index import PREVIEW_EXTS, PREVIEW_PRIMARY_MAX, SORTS, Index

logger = logging.getLogger("re-ddns.collections")

# ---------------------------------------------------------------------------
# Conventions (kept in sync with reflex_ddns_auth.collections; no import, the
# node must not depend on the app-side library)
# ---------------------------------------------------------------------------

META_DIR = ".item"                      # bookkeeping, hidden inside the item like .git/
MANIFEST_NAME = "manifest.json"
REPLICA_NAME = "replica.json"
FETCH_INFO_NAME = "fetch.json"
TMP_DIR = ".tmp"
BY_APP = "by-app"
PART_SUFFIX = ".part"
CONTAINER_ROOT = "/data/collections"          # where app containers see the tree
TOKEN_HEADER = "X-Re-DDNS-Node-Token"
ACCESS_LEVELS = ("read", "contribute", "contribute-only")
USER_OWNER = "_user"                           # the user's own imports (never an app's subdomain)
GENERIC_KIND = "file.generic"
THUMBNAIL_STEM = "thumbnail"                   # .item/thumbnail.<ext>, named by the manifest
THUMBNAIL_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
THUMBNAIL_MAX_BYTES = 512 * 1024
IMPORT_PREFIX = ".import."                     # <c>/by-app/_user/.tmp/.import.<upload>/ while importing
IMPORT_INFO = "import.json"
IMPORT_MAX_AGE = 24 * 3600                     # an upload nobody finished is dropped by _gc after this
DELETING_PREFIX = ".deleting."

_COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_OWNER_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,62}$")
_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_KIND_SEGMENT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_KIND_RE = re.compile(rf"^{_KIND_SEGMENT}(?:\.{_KIND_SEGMENT})+$")
_UPLOAD_RE = re.compile(r"^[0-9a-f]{32}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))


def valid_collection(name: str) -> bool:
    return bool(name) and bool(_COLLECTION_RE.match(name))


def valid_owner(name: str) -> bool:
    return bool(name) and bool(_OWNER_RE.match(name)) and name != BY_APP


def valid_item_id(name: str) -> bool:
    return bool(name) and bool(_ITEM_RE.match(name))


def valid_kind(kind: str) -> bool:
    """``<domain>.<type>``, e.g. ``dicom.series`` (the library's ``kinds.py`` rule)."""
    return isinstance(kind, str) and len(kind) <= 64 and bool(_KIND_RE.match(kind))


def _image_type(head: bytes) -> str | None:
    """The image type ``head`` (a file's first bytes) really is: png, jpg, gif, webp or None."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _checked_image(path: Path, max_bytes: int) -> tuple[Path, str] | None:
    """``(path, media type)`` when ``path`` is a real image file of at most ``max_bytes``."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            return None
        with open(path, "rb") as fh:
            kind = _image_type(fh.read(16))
    except OSError:
        return None
    return (path, THUMBNAIL_TYPES[kind]) if kind else None


def _thumbnail_name(manifest: dict) -> str:
    name = str(manifest.get("thumbnail") or "")
    stem, _, ext = name.partition(".")
    return name if stem == THUMBNAIL_STEM and ext in THUMBNAIL_TYPES else ""


def safe_relpath(rel: str) -> str:
    rel = str(rel).replace("\\", "/").strip()
    if not rel or rel.startswith("/") or rel.endswith("/"):
        raise ValueError(f"bad file path {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"bad file path {rel!r}")
    if parts[0] == META_DIR:
        raise ValueError(f"{META_DIR}/ is reserved for the item's bookkeeping")
    return "/".join(parts)


def _manifest(item_dir: Path) -> Path:
    return item_dir / META_DIR / MANIFEST_NAME


def _replica(item_dir: Path) -> Path:
    return item_dir / META_DIR / REPLICA_NAME


def _fetch_info(item_dir: Path) -> Path:
    return item_dir / META_DIR / FETCH_INFO_NAME


def parse_ref(text: str) -> tuple[str, str, str]:
    collection, sep, rest = str(text).partition(":")
    owner, sep2, item = rest.partition("/")
    if not (sep and sep2 and valid_collection(collection) and valid_owner(owner) and valid_item_id(item)):
        raise ValueError(f"invalid ref {text!r}")
    return collection, owner, item


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, data: dict) -> None:
    part = path.with_name(path.name + PART_SUFFIX)
    with open(part, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(part, path)


def _write_data_json(path: Path, data: dict) -> None:
    """``_write_json_atomic`` for files in re-ddns's own data folder.

    The temporary name keeps the ``.json`` ending: the dev-mode reloader
    watches that folder and would restart the backend for a ``.part`` file.
    """
    tmp = path.with_name(f"{path.stem}.{secrets.token_hex(4)}{path.suffix}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _tree_bytes(path: Path) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                try:
                    total += os.lstat(full).st_size
                except OSError:
                    pass
    return total


def _scan_payload(item_dir: Path) -> tuple[list[dict], list[str]]:
    """``(files, unfinished)`` below ``item_dir``, ``.item/`` and symlinks left out (as the library does)."""
    files: list[dict] = []
    unfinished: list[str] = []
    root = str(item_dir)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if not os.path.islink(os.path.join(dirpath, d)) and not (dirpath == root and d == META_DIR)
        )
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if name.endswith(PART_SUFFIX):
                unfinished.append(rel)
            else:
                files.append({"path": rel, "bytes": os.lstat(full).st_size})
    files.sort(key=lambda f: f["path"])
    return files, unfinished


def parse_peers(spec: str) -> dict[str, str]:
    """``"mac-b=http://192.168.1.20,nas=http://10.0.0.5"`` → ``{"mac-b": ..., "nas": ...}``."""
    peers: dict[str, str] = {}
    for part in (spec or "").split(","):
        name, sep, url = part.strip().partition("=")
        if sep and name.strip() and url.strip():
            peers[name.strip()] = url.strip().rstrip("/")
    return peers


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------

ClientFactory = Callable[[str], httpx.AsyncClient]


class Node:
    def __init__(
        self,
        root: "str | Path",
        name: str = "local",
        *,
        host_root: str = "",
        token: str = "",
        peers: dict[str, str] | None = None,
        peers_file: Path | None = None,
        peer_host_header: str = "",
        replica_max_bytes: int = 0,
        cache_seconds: float = 30.0,
        client_factory: ClientFactory | None = None,
        host_uid: int | None = None,
        host_gid: int | None = None,
        settings_file: Path | None = None,
        index_file: "Path | str | None" = None,
    ):
        self.root = Path(root)
        self.name = name or "local"
        self.host_root = host_root or str(self.root)
        self.token = token or ""
        self._env_peers = dict(peers or {})
        self.peers_file = peers_file
        self.peer_host_header = peer_host_header
        self.replica_max_bytes = int(replica_max_bytes or 0)
        self.cache_seconds = cache_seconds
        self._client_factory = client_factory
        self.host_uid = host_uid
        self.host_gid = host_gid
        self._peer_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
        self._peers_file_cache: tuple[float, dict[str, str]] = (-1.0, {})
        self._locks: dict[str, asyncio.Lock] = {}
        self._warned_open = False
        self.settings_file = settings_file
        self._settings_cache: tuple[float, dict] = (-1.0, {})
        self.index_file = index_file             # None: an in-memory index
        self._index: Index | None = None
        self._index_lock = threading.Lock()      # endpoints open it from worker threads

    @classmethod
    def from_env(cls) -> "Node":
        root_env = os.environ.get("COLLECTIONS_ROOT", "")
        root = Path(root_env) if root_env else (Path("/collections") if Path("/collections").is_dir() else _DATA_DIR / "collections")
        zone = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")

        def _int(name: str) -> int | None:
            raw = os.environ.get(name, "").strip()
            return int(raw) if raw.isdigit() else None

        return cls(
            root,
            os.environ.get("RE_DDNS_NODE_NAME") or socket.gethostname(),
            host_root=os.environ.get("COLLECTIONS_HOST_ROOT", ""),
            token=os.environ.get("RE_DDNS_NODE_TOKEN", ""),
            peers=parse_peers(os.environ.get("RE_DDNS_PEERS", "")),
            peers_file=_DATA_DIR / "collections_peers.json",
            peer_host_header=os.environ.get("RE_DDNS_PEER_HOST_HEADER", f"home.{zone}"),
            replica_max_bytes=int(os.environ.get("COLLECTIONS_REPLICA_MAX_BYTES", "0") or 0),
            host_uid=_int("HOST_UID"),
            host_gid=_int("HOST_GID"),
            settings_file=_DATA_DIR / "collections_settings.json",
            index_file=_DATA_DIR / "collections_index.sqlite",
        )

    @property
    def index(self) -> Index:
        """The searchable index of this host's items (opened on first use)."""
        with self._index_lock:
            if self._index is None:
                self._index = Index(self, self.index_file)
            return self._index

    # -- settings: the replica cap and quotas ------------------------------------

    @property
    def settings(self) -> dict:
        """``collections_settings.json``: what the storage page set (re-read when it changes)."""
        if self.settings_file is None:
            return {}
        try:
            mtime = self.settings_file.stat().st_mtime
        except OSError:
            mtime = -1.0
        if mtime != self._settings_cache[0]:
            self._settings_cache = (mtime, (_read_json(self.settings_file) or {}) if mtime >= 0 else {})
        return self._settings_cache[1]

    def update_settings(self, **changes: Any) -> dict:
        """Set (or, with ``None``, drop) top-level settings and write the file."""
        if self.settings_file is None:
            raise RuntimeError("this node has no settings file")
        data = dict(self.settings)
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        _write_data_json(self.settings_file, data)
        self._settings_cache = (-1.0, {})
        return self.settings

    def replica_cap(self) -> int:
        """Most bytes of replicas this host keeps (0 = no cap): the storage page's value, else the env's."""
        value = self.settings.get("replica_max_bytes")
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else self.replica_max_bytes

    def quotas(self) -> dict[str, dict[str, int]]:
        """``{collection: {owner: bytes}}``; an owner without an entry has no quota."""
        raw = self.settings.get("quotas")
        out: dict[str, dict[str, int]] = {}
        for collection, owners in (raw.items() if isinstance(raw, dict) else []):
            if isinstance(owners, dict):
                kept = {o: b for o, b in owners.items() if isinstance(b, int) and not isinstance(b, bool) and b > 0}
                if kept:
                    out[collection] = kept
        return out

    def set_quota(self, collection: str, owner: str, limit: int) -> dict[str, dict[str, int]]:
        if not (valid_collection(collection) and valid_owner(owner)):
            raise HTTPException(400, "invalid collection or owner")
        quotas = self.quotas()
        if limit > 0:
            quotas.setdefault(collection, {})[owner] = int(limit)
        else:
            quotas.get(collection, {}).pop(owner, None)
            quotas = {c: o for c, o in quotas.items() if o}
        self.update_settings(quotas=quotas or None)
        return self.quotas()

    def quota(self, collection: str, owner: str) -> dict:
        """``{"limit", "used"}`` in bytes: ``used`` counts the items ``owner`` published here."""
        self.index.sync()
        return {"limit": self.quotas().get(collection, {}).get(owner, 0),
                "used": self.index.used_bytes(collection, owner)}

    def check_quota(self, collection: str, owner: str, adding: int) -> None:
        q = self.quota(collection, owner)
        if q["limit"] and q["used"] + adding > q["limit"]:
            raise HTTPException(
                409, f"quota: {owner} may keep {q['limit']} bytes in {collection!r} here, has {q['used']}, "
                     f"and this needs {adding} more")

    # -- peers ---------------------------------------------------------------

    @property
    def peers(self) -> dict[str, str]:
        peers = dict(self._env_peers)
        if self.peers_file is not None:
            try:
                mtime = self.peers_file.stat().st_mtime
            except OSError:
                mtime = -1.0
            if mtime != self._peers_file_cache[0]:
                data = _read_json(self.peers_file) if mtime >= 0 else {}
                file_peers = (data or {}).get("peers") if isinstance((data or {}).get("peers"), dict) else {}
                self._peers_file_cache = (mtime, {str(k): str(v).rstrip("/") for k, v in file_peers.items() if v})
            peers.update(self._peers_file_cache[1])
        peers.pop(self.name, None)
        return peers

    def set_peers(self, peers: dict[str, str]) -> None:
        """Replace the peers kept in ``collections_peers.json`` (env peers stay)."""
        if self.peers_file is None:
            raise RuntimeError("this node has no peers file")
        self.peers_file.parent.mkdir(parents=True, exist_ok=True)
        _write_data_json(self.peers_file, {"peers": {k: v.rstrip("/") for k, v in peers.items()}})
        self._peer_cache.clear()

    def peer_client(self, url: str) -> httpx.AsyncClient:
        if self._client_factory is not None:
            return self._client_factory(url)
        headers = {}
        if self.token:
            headers[TOKEN_HEADER] = self.token
        if self.peer_host_header:
            headers["Host"] = self.peer_host_header
        return httpx.AsyncClient(base_url=url, headers=headers, timeout=httpx.Timeout(5.0, read=120.0))

    async def probe_peer(self, name: str, url: str) -> dict:
        """Is the peer answering, and does it call itself ``name``?"""
        try:
            async with self.peer_client(url) as client:
                r = await client.get("/api/collections/_peers")
                reported = str(r.json().get("node", "")) if r.status_code == 200 else ""
                return {"url": url, "reachable": r.status_code == 200, "node": reported,
                        "name_matches": reported == name}
        except (httpx.HTTPError, ValueError, OSError) as exc:
            return {"url": url, "reachable": False, "node": "", "name_matches": False, "error": str(exc)[:120]}

    def check_peer_token(self, request: Request) -> None:
        if not self.token:
            if not self._warned_open:
                logger.warning("RE_DDNS_NODE_TOKEN is empty: peer endpoints of /api/collections are open")
                self._warned_open = True
            return
        if request.headers.get(TOKEN_HEADER, "") != self.token:
            raise HTTPException(401, "missing or wrong node token")

    # -- paths ---------------------------------------------------------------

    def collection_dir(self, collection: str) -> Path:
        if not valid_collection(collection):
            raise HTTPException(400, f"invalid collection name {collection!r}")
        return self.root / collection

    def item_dir(self, collection: str, owner: str, item: str) -> Path:
        if not (valid_collection(collection) and valid_owner(owner) and valid_item_id(item)):
            raise HTTPException(400, "invalid collection, owner or item id")
        return self.root / collection / BY_APP / owner / item

    def _chown(self, *paths: Path) -> None:
        if self.host_uid is None:
            return
        for p in paths:
            try:
                st = os.lstat(p)
                if st.st_uid != self.host_uid:
                    os.chown(p, self.host_uid, self.host_gid if self.host_gid is not None else -1)
            except OSError:
                pass

    def _chown_tree(self, path: Path) -> None:
        if self.host_uid is None:
            return
        self._chown(path)
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            self._chown(*(Path(dirpath) / d for d in dirnames), *(Path(dirpath) / f for f in filenames))

    def ensure_collection(self, collection: str) -> Path:
        cdir = self.collection_dir(collection)
        by_app = cdir / BY_APP
        by_app.mkdir(parents=True, exist_ok=True)
        meta = cdir / "collection.json"
        if not meta.exists():
            _write_json_atomic(meta, {"name": collection, "created_at": _utcnow(), "created_by": self.name})
        self._chown(self.root, cdir, by_app, meta)
        return cdir

    def ensure_contribution(self, collection: str, owner: str) -> Path:
        if not valid_owner(owner):
            raise HTTPException(400, f"invalid owner {owner!r}")
        cdir = self.ensure_collection(collection)
        own = cdir / BY_APP / owner
        tmp = own / TMP_DIR
        tmp.mkdir(parents=True, exist_ok=True)
        self._chown(own, tmp)
        return own

    # -- local index -----------------------------------------------------------

    def collections(self) -> list[str]:
        try:
            return sorted(p.name for p in self.root.iterdir() if p.is_dir() and valid_collection(p.name))
        except OSError:
            return []

    def _entry(self, collection: str, owner: str, item_dir: Path) -> dict | None:
        manifest = _read_json(_manifest(item_dir))
        if manifest is None:
            return None
        replica = _read_json(_replica(item_dir)) if _replica(item_dir).exists() else None
        producer = manifest.get("producer") if isinstance(manifest.get("producer"), dict) else {}
        home = str((replica or {}).get("home") or producer.get("host") or self.name)
        return {
            "ref": f"{collection}:{owner}/{item_dir.name}",
            "collection": collection,
            "owner": owner,
            "id": item_dir.name,
            "kind": str(manifest.get("kind") or ""),
            "title": str(manifest.get("title") or item_dir.name),
            "created_at": str(manifest.get("created_at") or ""),
            "home": home if replica is not None else self.name,
            "local": True,
            "replica": replica is not None,
            "fetched_at": str((replica or {}).get("fetched_at") or ""),
            "bytes": int(manifest.get("bytes") or 0),
            "manifest": manifest,
        }

    def owner_entries(self, collection: str) -> list[os.DirEntry]:
        """The contribution directories ``by-app/<owner>/`` of ``collection``."""
        try:
            return [p for p in os.scandir(self.collection_dir(collection) / BY_APP)
                    if p.is_dir(follow_symlinks=False) and valid_owner(p.name)]
        except OSError:
            return []

    @staticmethod
    def item_entries(owner_dir: "str | Path") -> list[os.DirEntry]:
        """Directories in a contribution that may be items (``.tmp`` and other dot names never are)."""
        try:
            return [c for c in os.scandir(owner_dir) if c.is_dir(follow_symlinks=False) and valid_item_id(c.name)]
        except OSError:
            return []

    @staticmethod
    def manifest_path(item_dir: Path) -> Path:
        return _manifest(item_dir)

    @staticmethod
    def thumbnail_file(item_dir: Path, manifest: dict) -> tuple[Path, str] | None:
        """The item's own preview (``.item/thumbnail.*``) and its media type, when it is a real image."""
        name = _thumbnail_name(manifest)
        return _checked_image(item_dir / META_DIR / name, THUMBNAIL_MAX_BYTES) if name else None

    def preview(self, item_dir: Path, manifest: dict) -> tuple[Path, str] | None:
        """What the storage page shows for an item: its thumbnail, else a small image payload."""
        found = self.thumbnail_file(item_dir, manifest)
        if found is not None:
            return found
        primary = str(manifest.get("primary") or "")
        if not primary.lower().endswith(PREVIEW_EXTS):
            return None
        try:
            return _checked_image(item_dir / safe_relpath(primary), PREVIEW_PRIMARY_MAX)
        except ValueError:
            return None

    def local_items(self, collection: str, kind: str | None = None, owner: str | None = None) -> list[dict]:
        self.collection_dir(collection)            # 400 on a bad name
        entries: list[dict] = []
        for od in self.owner_entries(collection):
            if owner is not None and od.name != owner:
                continue
            for child in self.item_entries(od.path):
                entry = self._entry(collection, od.name, Path(child.path))
                if entry is not None and (kind is None or entry["kind"] == kind):
                    entries.append(entry)
        return entries

    def authoritative_items(self, collection: str, kind: str | None = None) -> list[dict]:
        return [e for e in self.local_items(collection, kind) if not e["replica"]]

    # -- peer index ---------------------------------------------------------------

    async def peer_items(self, collection: str, peer: str, url: str, fresh: bool = False) -> list[dict] | None:
        """Items whose home is ``peer`` (its authoritative items); ``None`` when unreachable."""
        key = (peer, collection)
        now = time.monotonic()
        cached = self._peer_cache.get(key)
        if cached and not fresh and now - cached[0] < self.cache_seconds:
            return cached[1]
        try:
            async with self.peer_client(url) as client:
                r = await client.get(f"/api/collections/{collection}/items", params={"scope": "authoritative"})
                if r.status_code != 200:
                    logger.warning("peer %s answered HTTP %s for %s", peer, r.status_code, collection)
                    return None
                items = [i for i in r.json().get("items", []) if isinstance(i, dict)]
        except (httpx.HTTPError, ValueError, OSError) as exc:
            logger.warning("peer %s unreachable: %s", peer, exc)
            return None
        entries = []
        for i in items:
            try:
                c, o, it = parse_ref(str(i.get("ref", "")))
            except ValueError:
                continue
            if c != collection:
                continue
            e = dict(i)
            e.update({"home": peer, "peer": peer, "local": False, "replica": False})
            entries.append(e)
        self._peer_cache[key] = (now, entries)
        return entries

    async def remote_items(self, collection: str, kind: str | None = None, fresh: bool = False) -> list[dict]:
        local_refs = {e["ref"] for e in self.local_items(collection)}
        found: dict[str, dict] = {}
        peers = self.peers
        results = await asyncio.gather(*(self.peer_items(collection, p, u, fresh) for p, u in peers.items()))
        for entries in results:
            for e in entries or []:
                if e["ref"] in local_refs or e["ref"] in found:
                    continue
                if kind is not None and e.get("kind") != kind:
                    continue
                found[e["ref"]] = e
        return list(found.values())

    async def items(self, collection: str, scope: str = "all", kind: str | None = None) -> list[dict]:
        if scope == "authoritative":
            entries = self.authoritative_items(collection, kind)
        elif scope == "local":
            entries = self.local_items(collection, kind)
        elif scope == "remote":
            entries = await self.remote_items(collection, kind)
        elif scope == "all":
            entries = self.local_items(collection, kind) + await self.remote_items(collection, kind)
        else:
            raise HTTPException(400, "scope must be all, local, remote or authoritative")
        entries.sort(key=lambda e: (e.get("created_at", ""), e["ref"]), reverse=True)
        return entries

    # -- transfer ------------------------------------------------------------------

    async def _locate(self, ref: str) -> tuple[str, str, dict] | None:
        collection = ref.split(":", 1)[0]
        for fresh in (False, True):
            for peer, url in self.peers.items():
                entries = await self.peer_items(collection, peer, url, fresh=fresh)
                for e in entries or []:
                    if e["ref"] == ref:
                        return peer, url, e
        return None

    def _done(self, final: Path, fetched: bool) -> dict:
        manifest = _read_json(_manifest(final)) or {}
        replica = _read_json(_replica(final))
        return {
            "ok": True, "local": True, "fetched": fetched, "replica": replica is not None,
            "home": str((replica or {}).get("home") or self.name), "bytes": int(manifest.get("bytes") or 0),
            "path": str(final),
        }

    async def fetch(self, ref: str) -> dict:
        """Make ``ref`` local: copy it from its home host unless it is here already."""
        try:
            collection, owner, item = parse_ref(ref)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        final = self.item_dir(collection, owner, item)
        if _manifest(final).exists():
            return self._done(final, fetched=False)
        lock = self._locks.setdefault(ref, asyncio.Lock())
        async with lock:
            if _manifest(final).exists():
                return self._done(final, fetched=False)
            located = await self._locate(ref)
            if located is None:
                raise HTTPException(404, f"{ref} is not on this host or on any known peer")
            peer, url, _entry = located
            tmp_root = final.parent / TMP_DIR
            tmp_root.mkdir(parents=True, exist_ok=True)
            self._chown(final.parent.parent, final.parent, tmp_root)
            tmp = tmp_root / f"{item}.replica.{secrets.token_hex(4)}"
            tmp.mkdir()
            base = f"/api/collections/{collection}/{BY_APP}/{owner}/{item}"
            try:
                async with self.peer_client(url) as client:
                    r = await client.get(f"{base}/{MANIFEST_NAME}")
                    if r.status_code != 200:
                        raise HTTPException(502, f"peer {peer} answered HTTP {r.status_code} for {ref}")
                    manifest = r.json()
                    files = [f for f in manifest.get("files", []) if isinstance(f, dict)]
                    total = sum(int(f.get("bytes") or 0) for f in files)
                    (tmp / META_DIR).mkdir(exist_ok=True)
                    _write_json_atomic(_fetch_info(tmp), {
                        "ref": ref, "home": peer, "bytes_total": total, "started_at": _utcnow(),
                    })
                    for f in files:
                        rel = safe_relpath(str(f.get("path", "")))
                        dest = tmp / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        part = dest.with_name(dest.name + PART_SUFFIX)
                        async with client.stream("GET", f"{base}/files/{rel}") as resp:
                            if resp.status_code != 200:
                                raise HTTPException(502, f"peer {peer} answered HTTP {resp.status_code} for {rel}")
                            with open(part, "wb") as fh:
                                async for chunk in resp.aiter_bytes(1024 * 1024):
                                    fh.write(chunk)
                        if part.stat().st_size != int(f.get("bytes") or 0):
                            raise HTTPException(502, f"size mismatch for {rel} from {peer}")
                        os.replace(part, dest)
                    thumb = _thumbnail_name(manifest)
                    if thumb:
                        # The preview is bookkeeping: a copy without it is still a full copy.
                        r = await client.get(f"{base}/thumbnail")
                        if (r.status_code == 200 and len(r.content) <= THUMBNAIL_MAX_BYTES
                                and _image_type(r.content[:16]) == thumb.partition(".")[2]):
                            (tmp / META_DIR / thumb).write_bytes(r.content)
                _fetch_info(tmp).unlink(missing_ok=True)
                _write_json_atomic(_replica(tmp), {"home": peer, "fetched_at": _utcnow(), "bytes": total})
                _write_json_atomic(_manifest(tmp), manifest)
                self._chown_tree(tmp)
                try:
                    os.rename(tmp, final)
                except OSError:
                    if _manifest(final).exists():
                        shutil.rmtree(tmp, ignore_errors=True)
                    else:
                        raise
            except HTTPException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            except (httpx.HTTPError, OSError, ValueError) as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(502, f"fetching {ref} from {peer} failed: {exc}") from exc
        self.enforce_replica_cap()
        return self._done(final, fetched=True)

    def fetch_status(self, ref: str) -> dict:
        try:
            collection, owner, item = parse_ref(ref)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        final = self.item_dir(collection, owner, item)
        manifest = _read_json(_manifest(final))
        if manifest is not None:
            size = int(manifest.get("bytes") or 0)
            return {"ref": ref, "state": "done", "bytes_done": size, "bytes_total": size}
        tmp_root = final.parent / TMP_DIR
        try:
            tmps = sorted(tmp_root.glob(f"{item}.replica.*"), key=lambda p: p.stat().st_mtime)
        except OSError:
            tmps = []
        if not tmps:
            return {"ref": ref, "state": "none", "bytes_done": 0, "bytes_total": 0}
        tmp = tmps[-1]
        info = _read_json(_fetch_info(tmp)) or {}
        return {
            "ref": ref, "state": "fetching", "home": info.get("home", ""),
            "bytes_done": _tree_bytes(tmp), "bytes_total": int(info.get("bytes_total") or 0),
        }

    # -- lifecycle -----------------------------------------------------------------

    def contributions_of(self, owner: str) -> list[dict]:
        if not valid_owner(owner):
            return []
        out = []
        for collection in self.collections():
            own = self.root / collection / BY_APP / owner
            if not own.is_dir():
                continue
            entries = self.local_items(collection, owner=owner)
            out.append({
                "collection": collection,
                "owner": owner,
                "path": f"{collection}/{BY_APP}/{owner}",
                "host_path": f"{self.host_root}/{collection}/{BY_APP}/{owner}",
                "items": sum(1 for e in entries if not e["replica"]),
                "replicas": sum(1 for e in entries if e["replica"]),
                "bytes": _tree_bytes(own),
            })
        return out

    def remove_contribution(self, collection: str, owner: str) -> bool:
        if not valid_owner(owner):
            return False
        own = self.collection_dir(collection) / BY_APP / owner
        if not own.is_dir():
            return False
        shutil.rmtree(own)
        return True

    def contributions(self, collection: str) -> list[dict]:
        by_app = self.collection_dir(collection) / BY_APP
        out = []
        try:
            owners = sorted(p.name for p in os.scandir(by_app) if p.is_dir(follow_symlinks=False) and valid_owner(p.name))
        except OSError:
            return out
        for owner in owners:
            entries = self.local_items(collection, owner=owner)
            out.append({
                "owner": owner,
                "items": sum(1 for e in entries if not e["replica"]),
                "replicas": sum(1 for e in entries if e["replica"]),
                "bytes": _tree_bytes(by_app / owner),
            })
        return out

    def replicas(self) -> list[dict]:
        out = []
        for collection in self.collections():
            out += [e for e in self.local_items(collection) if e["replica"]]
        return out

    def enforce_replica_cap(self) -> list[str]:
        cap = self.replica_cap()
        if cap <= 0:
            return []
        reps = sorted(self.replicas(), key=lambda e: e.get("fetched_at", ""))
        total = sum(e["bytes"] for e in reps)
        removed = []
        while reps and total > cap:
            victim = reps.pop(0)
            c, o, i = parse_ref(victim["ref"])
            shutil.rmtree(self.item_dir(c, o, i), ignore_errors=True)
            total -= victim["bytes"]
            removed.append(victim["ref"])
        return removed

    async def gc(self) -> dict:
        """Drop replicas their home no longer publishes, then enforce the size cap."""
        removed, kept, unknown = [], [], []
        peers = self.peers
        fresh_index: dict[tuple[str, str], set[str] | None] = {}
        for e in self.replicas():
            home = e["home"]
            if home not in peers:
                unknown.append(e["ref"])
                continue
            key = (home, e["collection"])
            if key not in fresh_index:
                entries = await self.peer_items(e["collection"], home, peers[home], fresh=True)
                fresh_index[key] = None if entries is None else {x["ref"] for x in entries}
            refs = fresh_index[key]
            if refs is None:
                kept.append(e["ref"])        # home unreachable: keep the copy
            elif e["ref"] in refs:
                kept.append(e["ref"])
            else:
                c, o, i = parse_ref(e["ref"])
                shutil.rmtree(self.item_dir(c, o, i), ignore_errors=True)
                removed.append(e["ref"])
        evicted = self.enforce_replica_cap()
        stale = self.drop_stale_staging()
        return {"removed": removed, "evicted": evicted, "kept": kept, "unknown_home": unknown,
                "stale_staging": stale}

    def drop_stale_staging(self, max_age: float = IMPORT_MAX_AGE) -> list[str]:
        """Imports nobody finished within ``max_age`` and deletions cut short, in every ``.tmp``."""
        dropped = []
        cutoff = time.time() - max_age
        for collection in self.collections():
            for od in self.owner_entries(collection):
                try:
                    staged = list(os.scandir(Path(od.path) / TMP_DIR))
                except OSError:
                    continue
                for entry in staged:
                    try:
                        old = entry.stat(follow_symlinks=False).st_mtime < cutoff
                    except OSError:
                        continue
                    if entry.name.startswith(DELETING_PREFIX) or (entry.name.startswith(IMPORT_PREFIX) and old):
                        shutil.rmtree(entry.path, ignore_errors=True)
                        dropped.append(f"{collection}/{BY_APP}/{od.name}/{TMP_DIR}/{entry.name}")
        return dropped

    # -- managing items (the storage page) -------------------------------------------

    def remove_item(self, collection: str, owner: str, item: str) -> dict:
        """Delete one local item, or a local replica (any owner: this is the admin's call)."""
        d = self.item_dir(collection, owner, item)
        if d.is_symlink() or not _manifest(d).exists():
            raise HTTPException(404, "no such item on this host")
        replica = _replica(d).exists()
        ref = f"{collection}:{owner}/{item}"
        # Out of sight with one rename, then deleted: readers never see half an item.
        trash = d.parent / TMP_DIR / f"{DELETING_PREFIX}{item}.{secrets.token_hex(4)}"
        trash.parent.mkdir(parents=True, exist_ok=True)
        os.rename(d, trash)
        shutil.rmtree(trash, ignore_errors=True)
        self.index.forget(ref)
        return {"removed": ref, "replica": replica}

    def usage(self) -> dict:
        """Space per collection and contribution, the replica cap, quotas and the disk."""
        self.index.sync()
        per = self.index.usage()
        quotas = self.quotas()
        collections, replica_bytes = [], 0
        for collection in self.collections():
            owners = []
            for od in sorted(self.owner_entries(collection), key=lambda e: e.name):
                u = per.get((collection, od.name), {"items": 0, "bytes": 0, "replicas": 0, "replica_bytes": 0})
                owners.append({
                    "owner": od.name, **u,
                    "staging_bytes": _tree_bytes(Path(od.path) / TMP_DIR),
                    "quota": quotas.get(collection, {}).get(od.name, 0),
                })
            totals = {k: sum(o[k] for o in owners) for k in ("items", "bytes", "replicas", "replica_bytes", "staging_bytes")}
            replica_bytes += totals["replica_bytes"]
            collections.append({"name": collection, **totals, "owners": owners})
        try:
            du = shutil.disk_usage(self.root)
            disk = {"total": du.total, "used": du.used, "free": du.free}
        except OSError:
            disk = {}
        return {
            "node": self.name, "host_root": self.host_root, "container_root": CONTAINER_ROOT,
            "disk": disk, "collections": collections, "replica_bytes": replica_bytes,
            "replica_cap": self.replica_cap(), "replica_cap_env": self.replica_max_bytes,
            "node_token": bool(self.token),
        }

    # -- importing a user's own files (owner _user) --------------------------------

    def _import_staging(self, upload: str) -> Path:
        if not _UPLOAD_RE.match(upload or ""):
            raise HTTPException(400, "bad upload id")
        for collection in self.collections():
            d = self.root / collection / BY_APP / USER_OWNER / TMP_DIR / f"{IMPORT_PREFIX}{upload}"
            if d.is_dir() and not d.is_symlink():
                return d
        raise HTTPException(404, "no such upload (finished, discarded or expired)")

    def import_begin(self, collection: str, kind: str, title: str = "", meta: dict | None = None) -> dict:
        """Open an upload; its files arrive with ``import_file``, ``import_finish`` publishes them."""
        if not valid_collection(collection):
            raise HTTPException(400, f"invalid collection name {collection!r}")
        if not valid_kind(kind):
            raise HTTPException(400, f"invalid kind {kind!r}: use <domain>.<type>, e.g. {GENERIC_KIND}")
        if meta is not None and (not isinstance(meta, dict) or len(json.dumps(meta)) > 16_000):
            raise HTTPException(400, "meta must be a small JSON object")
        own = self.ensure_contribution(collection, USER_OWNER)
        upload = secrets.token_hex(16)
        staging = own / TMP_DIR / f"{IMPORT_PREFIX}{upload}"
        (staging / META_DIR).mkdir(parents=True)
        _write_json_atomic(staging / META_DIR / IMPORT_INFO, {
            "collection": collection, "kind": kind, "title": (title or "").strip()[:200],
            "meta": meta or {}, "started_at": _utcnow(),
        })
        self._chown(staging, staging / META_DIR)
        return {"upload": upload, "collection": collection, "owner": USER_OWNER}

    async def import_file(self, upload: str, path: str, chunks: AsyncIterator[bytes]) -> dict:
        staging = self._import_staging(upload)
        try:
            rel = safe_relpath(path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        info = _read_json(staging / META_DIR / IMPORT_INFO) or {}
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + PART_SUFFIX)
        written = 0
        try:
            with open(part, "wb") as fh:
                async for chunk in chunks:
                    fh.write(chunk)
                    written += len(chunk)
            os.replace(part, dest)
            files, _ = _scan_payload(staging)
            await asyncio.to_thread(
                self.check_quota, str(info.get("collection", "")), USER_OWNER, sum(f["bytes"] for f in files))
        except BaseException:
            part.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            raise
        return {"path": rel, "bytes": written}

    def _import_id(self, collection: str, title: str) -> str:
        stem = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title or "").strip("-._")[:60]
        stem = f"{stem}-{slug}" if slug else stem
        own = self.root / collection / BY_APP / USER_OWNER
        candidate, n = stem, 2
        while (own / candidate).exists():
            candidate, n = f"{stem}-{n}", n + 1
        return candidate

    def import_finish(self, upload: str) -> dict:
        """Publish the upload as an item of ``_user``: manifest last, then one rename."""
        staging = self._import_staging(upload)
        info = _read_json(staging / META_DIR / IMPORT_INFO)
        if info is None:
            raise HTTPException(409, "this upload is already being finished")
        collection, kind = str(info.get("collection", "")), str(info.get("kind", GENERIC_KIND))
        files, unfinished = _scan_payload(staging)
        if unfinished:
            raise HTTPException(400, f"files still uploading: {', '.join(unfinished)}")
        if not files:
            raise HTTPException(400, "the upload has no files")
        total = sum(f["bytes"] for f in files)
        self.check_quota(collection, USER_OWNER, total)
        title = str(info.get("title") or "")
        item_id = self._import_id(collection, title)
        manifest = {
            "schema": 1, "collection": collection, "owner": USER_OWNER, "id": item_id, "kind": kind,
            "title": title or item_id, "created_at": _utcnow(),
            "producer": {"app": USER_OWNER, "host": self.name},
            "source": "", "derived_from": [], "primary": files[0]["path"] if len(files) == 1 else "",
            "files": files, "bytes": total, "meta": info.get("meta") if isinstance(info.get("meta"), dict) else {},
        }
        (staging / META_DIR / IMPORT_INFO).unlink()
        _write_json_atomic(_manifest(staging), manifest)
        self._chown_tree(staging)
        final = staging.parent.parent / item_id
        os.rename(staging, final)
        entry = self._entry(collection, USER_OWNER, final) or {}
        entry.pop("manifest", None)
        return entry

    def import_discard(self, upload: str) -> dict:
        shutil.rmtree(self._import_staging(upload), ignore_errors=True)
        return {"discarded": upload}


# ---------------------------------------------------------------------------
# Catalog ``storage`` → container mounts + env
# ---------------------------------------------------------------------------

class StorageSpec(BaseModel):
    """One entry of a catalog app's ``storage`` list."""
    collection: str
    access: str = "contribute"      # read | contribute | contribute-only
    env: str = ""                   # legacy env var to set, e.g. PUBLIC_DICOM_DIR
    env_target: str = "root"        # root (the collection) | own (the app's contribution)


def storage_binds(node: Node, subdomain: str, storage: list[StorageSpec]) -> tuple[list[str], list[str]]:
    """``(binds, env)`` for an app container.  Raises ``ValueError`` on a bad declaration."""
    if not valid_owner(subdomain):
        raise ValueError(f"subdomain {subdomain!r} cannot be a collection owner")
    binds: list[str] = []
    env: list[str] = []
    for spec in storage or []:
        collection = (spec.collection or "").strip()
        if not valid_collection(collection):
            raise ValueError(f"storage: invalid collection name {collection!r}")
        access = (spec.access or "contribute").strip()
        if access not in ACCESS_LEVELS:
            raise ValueError(f"storage: access must be one of {', '.join(ACCESS_LEVELS)}")
        host_c = f"{node.host_root.rstrip('/')}/{collection}"
        ctr_c = f"{CONTAINER_ROOT}/{collection}"
        node.ensure_collection(collection)
        if access in ("read", "contribute"):
            binds.append(f"{host_c}:{ctr_c}:ro")
        if access in ("contribute", "contribute-only"):
            node.ensure_contribution(collection, subdomain)
            binds.append(f"{host_c}/{BY_APP}/{subdomain}:{ctr_c}/{BY_APP}/{subdomain}:rw")
        if spec.env:
            key = spec.env.strip()
            if not _ENV_RE.match(key):
                raise ValueError(f"storage: bad env var name {key!r}")
            value = f"{ctr_c}/{BY_APP}/{subdomain}" if spec.env_target == "own" else ctr_c
            env.append(f"{key}={value}")
    env.append(f"DDNS_APP_ID={subdomain}")
    env.append(f"DDNS_NODE_NAME={node.name}")
    if storage:
        env.append(f"DDNS_COLLECTIONS_ROOT={CONTAINER_ROOT}")
        env.append("DDNS_COLLECTIONS_NODE_URL=http://re-ddns:8000")
    return binds, env


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class FetchRequest(BaseModel):
    ref: str


class PeersRequest(BaseModel):
    peers: dict[str, str]


class QuotaRequest(BaseModel):
    collection: str
    owner: str
    bytes: int = 0                      # 0 removes the quota


class SettingsRequest(BaseModel):
    replica_max_bytes: int | None = None   # left out: unchanged; null: back to the env value
    quota: QuotaRequest | None = None


class ImportRequest(BaseModel):
    collection: str
    kind: str = GENERIC_KIND
    title: str = ""
    meta: dict[str, Any] = {}


def _light(entry: dict) -> dict:
    """An index row's shape for an item another host serves (its manifest came along)."""
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    files = [f for f in manifest.get("files", []) if isinstance(f, dict)]
    primary = str(manifest.get("primary") or "")
    size_of = next((int(f.get("bytes") or 0) for f in files if f.get("path") == primary), 0)
    preview = "thumbnail" if _thumbnail_name(manifest) else (
        "primary" if primary.lower().endswith(PREVIEW_EXTS) and 0 < size_of <= PREVIEW_PRIMARY_MAX else "")
    producer = manifest.get("producer") if isinstance(manifest.get("producer"), dict) else {}
    return {
        "ref": entry["ref"], "collection": entry.get("collection") or entry["ref"].split(":", 1)[0],
        "owner": entry.get("owner", ""), "id": entry.get("id", ""), "kind": str(entry.get("kind") or ""),
        "title": str(entry.get("title") or ""), "created_at": str(entry.get("created_at") or ""),
        "bytes": int(entry.get("bytes") or 0), "files": len(files), "local": False, "replica": False,
        "home": str(entry.get("home") or ""), "fetched_at": "", "primary": primary, "preview": preview,
        "source": str(manifest.get("source") or ""), "producer": str(producer.get("app") or ""),
        "meta": manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {},
        "derived_from": [r for r in manifest.get("derived_from", []) if isinstance(r, str)],
    }


def _matches(row: dict, kind: str | None, owner: str | None, q: str | None) -> bool:
    if (kind and row["kind"] != kind) or (owner and row["owner"] != owner):
        return False
    text = " ".join([row["title"], row["id"], row["kind"], row["owner"], row["source"], row["home"],
                     *(str(v) for v in row["meta"].values())]).lower()
    return all(word in text for word in (q or "").lower().split())


def _sorted(rows: list[dict], sort: str) -> list[dict]:
    keys = {
        "newest": (lambda r: (r["created_at"], r["ref"]), True),
        "oldest": (lambda r: (r["created_at"], r["ref"]), False),
        "largest": (lambda r: (r["bytes"], r["ref"]), True),
        "smallest": (lambda r: (r["bytes"], r["ref"]), False),
        "title": (lambda r: (r["title"].lower(), r["ref"]), False),
    }
    key, reverse = keys.get(sort, keys["newest"])
    return sorted(rows, key=key, reverse=reverse)


def build_router(node: Node) -> APIRouter:
    router = APIRouter(prefix="/api/collections", tags=["collections"])
    admin = [Depends(require_admin)]

    @router.get("")
    async def overview():
        peers = node.peers
        probes = await asyncio.gather(*(node.probe_peer(n, u) for n, u in peers.items()))
        status = {n: probe for n, probe in zip(peers, probes)}
        return {
            "node": node.name,
            "root": str(node.root),
            "host_root": node.host_root,
            "container_root": CONTAINER_ROOT,
            "peers": status,
            "replica_max_bytes": node.replica_cap(),
            "collections": [
                {"name": c, "contributions": node.contributions(c)} for c in node.collections()
            ],
        }

    @router.get("/_peers")
    async def get_peers():
        # from_env: peers set by RE_DDNS_PEERS, which a PUT cannot remove.
        return {"node": node.name, "peers": node.peers, "from_env": sorted(node._env_peers)}

    @router.put("/_peers", dependencies=admin)
    async def put_peers(req: PeersRequest):
        for name, url in req.peers.items():
            if not valid_owner(name) or not url.startswith(("http://", "https://")):
                raise HTTPException(400, f"bad peer {name!r}: name like a hostname, url with http(s)://")
        node.set_peers(req.peers)
        return {"node": node.name, "peers": node.peers}

    @router.get("/_contributions/{owner}", dependencies=admin)
    async def contributions_of(owner: str):
        return {"owner": owner, "contributions": node.contributions_of(owner)}

    @router.delete("/_contributions/{owner}", dependencies=admin)
    async def delete_contributions(owner: str, collection: str | None = None):
        removed = []
        for c in ([collection] if collection else node.collections()):
            if node.remove_contribution(c, owner):
                removed.append(c)
        return {"owner": owner, "removed": removed}

    @router.post("/_gc", dependencies=admin)
    async def gc():
        return await node.gc()

    # -- the storage page ------------------------------------------------------------

    @router.get("/_usage", dependencies=admin)
    async def usage():
        return await asyncio.to_thread(node.usage)

    @router.get("/_index", dependencies=admin)
    async def index(
        collection: str | None = None,
        kind: str | None = None,
        owner: str | None = None,
        q: str | None = None,
        location: str = "all",           # all | here | own | replica | remote
        sort: str = "newest",
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        refresh: bool = False,
    ):
        if location not in ("all", "here", "own", "replica", "remote"):
            raise HTTPException(400, "location must be all, here, own, replica or remote")
        if sort not in SORTS:
            raise HTTPException(400, f"sort must be one of {', '.join(SORTS)}")
        if collection and not valid_collection(collection):
            raise HTTPException(400, f"invalid collection name {collection!r}")
        synced = await asyncio.to_thread(node.index.sync, refresh)
        rows, total = [], 0
        if location != "remote":
            rows, total = await asyncio.to_thread(
                node.index.query, collection=collection, kind=kind, owner=owner, q=q,
                location={"own": "own", "replica": "replica"}.get(location), sort=sort,
                limit=offset + limit, offset=0,
            )
        remote: list[dict] = []
        if location in ("all", "remote") and node.peers:
            # Other hosts' items of the collections this host has (its apps can use only those).
            for c in ([collection] if collection else node.collections()):
                remote += [r for r in map(_light, await node.remote_items(c)) if _matches(r, kind, owner, q)]
        merged = _sorted(rows + remote, sort)[offset:offset + limit]
        facets = await asyncio.to_thread(node.index.facets)
        for r in remote:
            for name, value in (("collections", r["collection"]), ("kinds", r["kind"]), ("owners", r["owner"])):
                f = next((f for f in facets[name] if f["value"] == value), None)
                if f is None:
                    facets[name].append({"value": value, "items": 1})
                else:
                    f["items"] += 1
        return {"node": node.name, "items": merged, "total": total + len(remote), "facets": facets,
                "synced": synced}

    @router.get("/_item", dependencies=admin)
    async def item(ref: str):
        try:
            c, o, i = parse_ref(ref)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        d = node.item_dir(c, o, i)
        entry = node._entry(c, o, d)
        if entry is not None:
            entry["preview"] = "" if node.preview(d, entry["manifest"]) is None else (
                "thumbnail" if node.thumbnail_file(d, entry["manifest"]) else "primary")
            entry["host_path"] = f"{node.host_root}/{c}/{BY_APP}/{o}/{i}"
            entry["container_path"] = f"{CONTAINER_ROOT}/{c}/{BY_APP}/{o}/{i}"
        else:
            located = await node._locate(ref)
            if located is None:
                raise HTTPException(404, f"{ref} is not on this host or on any known peer")
            entry = {**located[2], **{k: v for k, v in _light(located[2]).items() if k == "preview"}}
        await asyncio.to_thread(node.index.sync)
        derived = entry.get("manifest", {}).get("derived_from", []) if isinstance(entry.get("manifest"), dict) else []
        entry["derived_from_items"] = []
        for parent in [r for r in derived if isinstance(r, str)]:
            row = node.index.get(parent)
            entry["derived_from_items"].append(
                {"ref": parent, "title": row["title"] if row else "", "kind": row["kind"] if row else "",
                 "here": row is not None})
        entry["derived_into"] = [
            {"ref": r["ref"], "title": r["title"], "kind": r["kind"], "owner": r["owner"]}
            for r in node.index.derived_into(ref)
        ]
        return entry

    @router.get("/_thumb", dependencies=admin)
    async def thumb(ref: str):
        try:
            c, o, i = parse_ref(ref)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        cache = {"Cache-Control": "private, max-age=600"}
        d = node.item_dir(c, o, i)
        manifest = _read_json(_manifest(d))
        if manifest is not None:
            found = node.preview(d, manifest)
            if found is None:
                raise HTTPException(404, "this item has no preview")
            return FileResponse(str(found[0]), media_type=found[1], headers=cache)
        located = await node._locate(ref)
        if located is None:
            raise HTTPException(404, f"{ref} is not on this host or on any known peer")
        peer, url, entry = located
        light = _light(entry)
        base = f"/api/collections/{c}/{BY_APP}/{o}/{i}"
        path = {"thumbnail": f"{base}/thumbnail", "primary": f"{base}/files/{light['primary']}"}.get(light["preview"])
        if path is None:
            raise HTTPException(404, "this item has no preview")
        try:
            async with node.peer_client(url) as client:
                r = await client.get(path)
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"peer {peer} unreachable: {exc}") from exc
        kind = _image_type(r.content[:16]) if r.status_code == 200 else None
        if kind is None or len(r.content) > PREVIEW_PRIMARY_MAX:
            raise HTTPException(404, "this item has no preview")
        return Response(r.content, media_type=THUMBNAIL_TYPES[kind], headers=cache)

    @router.get("/_settings", dependencies=admin)
    async def get_settings():
        return {"replica_max_bytes": node.replica_cap(), "replica_max_bytes_env": node.replica_max_bytes,
                "replica_max_bytes_set": "replica_max_bytes" in node.settings, "quotas": node.quotas()}

    @router.put("/_settings", dependencies=admin)
    async def put_settings(req: SettingsRequest):
        given = getattr(req, "model_fields_set", None) or getattr(req, "__fields_set__", set())
        evicted: list[str] = []
        if "replica_max_bytes" in given:
            if req.replica_max_bytes is not None and req.replica_max_bytes < 0:
                raise HTTPException(400, "replica_max_bytes must be 0 (no cap) or more")
            node.update_settings(replica_max_bytes=req.replica_max_bytes)
            evicted = await asyncio.to_thread(node.enforce_replica_cap)
        if req.quota is not None:
            if req.quota.bytes < 0:
                raise HTTPException(400, "a quota is 0 (none) or more bytes")
            node.set_quota(req.quota.collection, req.quota.owner, req.quota.bytes)
        return {**(await get_settings()), "evicted": evicted}

    @router.post("/_import", dependencies=admin)
    async def import_begin(req: ImportRequest):
        return await asyncio.to_thread(node.import_begin, req.collection, req.kind, req.title, req.meta)

    @router.put("/_import/{upload}/files/{path:path}", dependencies=admin)
    async def import_file(request: Request, upload: str, path: str):
        return await node.import_file(upload, path, request.stream())

    @router.post("/_import/{upload}/finish", dependencies=admin)
    async def import_finish(upload: str):
        return await asyncio.to_thread(node.import_finish, upload)

    @router.delete("/_import/{upload}", dependencies=admin)
    async def import_discard(upload: str):
        return await asyncio.to_thread(node.import_discard, upload)

    # -- what apps use -------------------------------------------------------------------

    @router.get("/{collection}/quota/{owner}")
    async def quota(collection: str, owner: str):
        if not (valid_collection(collection) and valid_owner(owner)):
            raise HTTPException(400, "invalid collection or owner")
        return {"collection": collection, "owner": owner, **(await asyncio.to_thread(node.quota, collection, owner))}

    @router.get("/{collection}/items")
    async def items(request: Request, collection: str, scope: str = "all", kind: str | None = Query(default=None)):
        if scope == "authoritative":
            node.check_peer_token(request)
        return {"collection": collection, "node": node.name, "items": await node.items(collection, scope, kind)}

    @router.post("/{collection}/fetch")
    async def fetch(collection: str, req: FetchRequest):
        if not req.ref.startswith(f"{collection}:"):
            raise HTTPException(400, f"ref {req.ref!r} is not in collection {collection!r}")
        return await node.fetch(req.ref)

    @router.get("/{collection}/fetch-status")
    async def fetch_status(collection: str, ref: str):
        if not ref.startswith(f"{collection}:"):
            raise HTTPException(400, f"ref {ref!r} is not in collection {collection!r}")
        return node.fetch_status(ref)

    @router.get(f"/{{collection}}/{BY_APP}/{{owner}}/{{item}}/{MANIFEST_NAME}")
    async def manifest(request: Request, collection: str, owner: str, item: str):
        node.check_peer_token(request)
        d = node.item_dir(collection, owner, item)
        data = _read_json(_manifest(d))
        if data is None or _replica(d).exists():
            raise HTTPException(404, "no such item on this host")
        return data

    @router.get(f"/{{collection}}/{BY_APP}/{{owner}}/{{item}}/files/{{path:path}}")
    async def file(request: Request, collection: str, owner: str, item: str, path: str):
        node.check_peer_token(request)
        d = node.item_dir(collection, owner, item)
        data = _read_json(_manifest(d))
        if data is None or _replica(d).exists():
            raise HTTPException(404, "no such item on this host")
        try:
            rel = safe_relpath(path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if rel not in {str(f.get("path")) for f in data.get("files", []) if isinstance(f, dict)}:
            raise HTTPException(404, "no such file in the item")
        full = d / rel
        if full.is_symlink() or not full.is_file():
            raise HTTPException(404, "no such file in the item")
        return FileResponse(str(full), media_type="application/octet-stream", filename=full.name)

    @router.get(f"/{{collection}}/{BY_APP}/{{owner}}/{{item}}/thumbnail")
    async def thumbnail(request: Request, collection: str, owner: str, item: str):
        node.check_peer_token(request)
        d = node.item_dir(collection, owner, item)
        data = _read_json(_manifest(d))
        if data is None or _replica(d).exists():
            raise HTTPException(404, "no such item on this host")
        found = node.thumbnail_file(d, data)
        if found is None:
            raise HTTPException(404, "this item has no thumbnail")
        return FileResponse(str(found[0]), media_type=found[1])

    @router.delete(f"/{{collection}}/{BY_APP}/{{owner}}/{{item}}", dependencies=admin)
    async def delete_item(collection: str, owner: str, item: str):
        return await asyncio.to_thread(node.remove_item, collection, owner, item)

    return router


node = Node.from_env()
router = build_router(node)
