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

Configuration (environment):

    COLLECTIONS_ROOT             where this container sees the tree (default /collections)
    COLLECTIONS_HOST_ROOT        the same directory on the Docker host, used for binds
    RE_DDNS_NODE_NAME            this host's name in refs' ``home`` (default: hostname)
    RE_DDNS_PEERS                "name=url,name=url" of other re-ddns nodes; the file
                                 ``<data>/collections_peers.json`` {"peers": {...}} is merged in
    RE_DDNS_NODE_TOKEN           shared secret peers must present (header X-Re-DDNS-Node-Token)
    RE_DDNS_PEER_HOST_HEADER     Host header sent to peers (default home.<zone>, so a peer's
                                 nginx routes the request to its re-ddns backend)
    COLLECTIONS_REPLICA_MAX_BYTES  cap on replica bytes per host; 0 = unlimited
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
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

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

_COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_OWNER_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,62}$")
_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))


def valid_collection(name: str) -> bool:
    return bool(name) and bool(_COLLECTION_RE.match(name))


def valid_owner(name: str) -> bool:
    return bool(name) and bool(_OWNER_RE.match(name)) and name != BY_APP


def valid_item_id(name: str) -> bool:
    return bool(name) and bool(_ITEM_RE.match(name))


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
        )

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
        _write_json_atomic(self.peers_file, {"peers": {k: v.rstrip("/") for k, v in peers.items()}})
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

    def local_items(self, collection: str, kind: str | None = None, owner: str | None = None) -> list[dict]:
        by_app = self.collection_dir(collection) / BY_APP
        entries: list[dict] = []
        try:
            owners = [p for p in os.scandir(by_app) if p.is_dir(follow_symlinks=False) and valid_owner(p.name)]
        except OSError:
            return entries
        for od in owners:
            if owner is not None and od.name != owner:
                continue
            try:
                children = [c for c in os.scandir(od.path) if c.is_dir(follow_symlinks=False) and valid_item_id(c.name)]
            except OSError:
                continue
            for child in children:
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
        if self.replica_max_bytes <= 0:
            return []
        reps = sorted(self.replicas(), key=lambda e: e.get("fetched_at", ""))
        total = sum(e["bytes"] for e in reps)
        removed = []
        while reps and total > self.replica_max_bytes:
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
        return {"removed": removed, "evicted": evicted, "kept": kept, "unknown_home": unknown}


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


def build_router(node: Node) -> APIRouter:
    router = APIRouter(prefix="/api/collections", tags=["collections"])

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
            "replica_max_bytes": node.replica_max_bytes,
            "collections": [
                {"name": c, "contributions": node.contributions(c)} for c in node.collections()
            ],
        }

    @router.get("/_peers")
    async def get_peers():
        return {"node": node.name, "peers": node.peers}

    @router.put("/_peers")
    async def put_peers(req: PeersRequest):
        for name, url in req.peers.items():
            if not valid_owner(name) or not url.startswith(("http://", "https://")):
                raise HTTPException(400, f"bad peer {name!r}: name like a hostname, url with http(s)://")
        node.set_peers(req.peers)
        return {"node": node.name, "peers": node.peers}

    @router.get("/_contributions/{owner}")
    async def contributions_of(owner: str):
        return {"owner": owner, "contributions": node.contributions_of(owner)}

    @router.delete("/_contributions/{owner}")
    async def delete_contributions(owner: str, collection: str | None = None):
        removed = []
        for c in ([collection] if collection else node.collections()):
            if node.remove_contribution(c, owner):
                removed.append(c)
        return {"owner": owner, "removed": removed}

    @router.post("/_gc")
    async def gc():
        return await node.gc()

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

    return router


node = Node.from_env()
router = build_router(node)
