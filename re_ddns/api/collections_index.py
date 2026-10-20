"""A disposable SQLite index of this host's collection tree, for the storage page.

The tree on disk is the truth: apps write it directly and read plain paths,
and nothing about an item lives only here.  The index lets the App Store's
storage page search, sort, page and total many items without reading every
manifest each time, and answer "which items were made from this one"
(``derived_from`` read backwards).  Delete the file and it is rebuilt from
the manifests on the next ``sync()``.

Keeping up without a hook into the writers: publishing, fetching a replica,
importing and deleting all add or remove an entry of ``by-app/<owner>/``,
which changes that directory's mtime.  ``sync()`` re-lists only the owners
whose mtime moved and re-reads only the manifests whose (mtime, size)
changed.  Every ``FULL_EVERY`` seconds, and on ``sync(full=True)``, it
re-lists every owner, in case a file system reports directory times late.

The index only reads the tree through the node it is given (``Node`` in
``collections_api``), so both agree on what an item is.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("re-ddns.collections.index")

SCHEMA = 2                    # bump when what a row holds changes: the index is rebuilt
FULL_EVERY = 300.0
PREVIEW_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
PREVIEW_PRIMARY_MAX = 2 * 1024 * 1024

SORTS = {
    "newest": "created_at DESC, ref",
    "oldest": "created_at ASC, ref",
    "largest": "bytes DESC, ref",
    "smallest": "bytes ASC, ref",
    "title": "title COLLATE NOCASE ASC, ref",
}

_COLUMNS = (
    "ref", "collection", "owner", "id", "kind", "title", "created_at", "bytes", "files", "replica",
    "home", "fetched_at", "primary_file", "preview", "source", "producer", "meta", "derived_from",
)

_DDL = """
CREATE TABLE IF NOT EXISTS items (
    ref TEXT PRIMARY KEY, collection TEXT NOT NULL, owner TEXT NOT NULL, id TEXT NOT NULL,
    kind TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, bytes INTEGER NOT NULL,
    files INTEGER NOT NULL, replica INTEGER NOT NULL, home TEXT NOT NULL, fetched_at TEXT NOT NULL,
    primary_file TEXT NOT NULL, preview TEXT NOT NULL, source TEXT NOT NULL, producer TEXT NOT NULL,
    meta TEXT NOT NULL, derived_from TEXT NOT NULL, search TEXT NOT NULL,
    manifest_mtime INTEGER NOT NULL, manifest_size INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS items_owner ON items (collection, owner);
CREATE INDEX IF NOT EXISTS items_kind ON items (kind);
CREATE INDEX IF NOT EXISTS items_created ON items (created_at);
CREATE TABLE IF NOT EXISTS lineage (ref TEXT NOT NULL, parent TEXT NOT NULL, PRIMARY KEY (ref, parent));
CREATE INDEX IF NOT EXISTS lineage_parent ON lineage (parent);
CREATE TABLE IF NOT EXISTS owners (
    collection TEXT NOT NULL, owner TEXT NOT NULL, mtime INTEGER NOT NULL, PRIMARY KEY (collection, owner)
);
"""


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Index:
    def __init__(self, node: Any, path: "str | Path | None" = None):
        self.node = node
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._last_full = 0.0
        self.synced_at = 0.0
        self._db = self._open()

    # -- storage -------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path) if self.path else ":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        # No journal or WAL files next to the database: re-ddns's dev-mode reloader
        # watches its data folder and ignores only *.sqlite there, so a -wal or
        # -journal file would restart the backend.  A crash mid-write can then
        # corrupt the file, which costs nothing but a rebuild (quick_check below).
        db.execute("PRAGMA journal_mode=MEMORY")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA temp_store=MEMORY")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("quick_check failed")
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
            db.executescript("DROP TABLE IF EXISTS items; DROP TABLE IF EXISTS lineage; DROP TABLE IF EXISTS owners;")
            db.execute(f"PRAGMA user_version={SCHEMA}")
        db.executescript(_DDL)
        db.commit()
        return db

    def _open(self) -> sqlite3.Connection:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connect()
        except sqlite3.DatabaseError as exc:
            if not self.path:
                raise
            # The index is disposable: start over from the manifests.
            logger.warning("collections index %s unreadable (%s); rebuilding it", self.path, exc)
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)
            return self._connect()

    # -- keeping up with the tree -----------------------------------------------

    def sync(self, full: bool = False) -> dict:
        """Bring the index up to date with the tree; cheap when nothing changed."""
        with self._lock:
            started = time.time()
            full = full or started - self._last_full >= FULL_EVERY
            db = self._db
            known = {(r["collection"], r["owner"]): r["mtime"] for r in db.execute("SELECT * FROM owners")}
            seen: set[tuple[str, str]] = set()
            changed = 0
            for collection in self.node.collections():
                for entry in self.node.owner_entries(collection):
                    key = (collection, entry.name)
                    try:
                        mtime = entry.stat(follow_symlinks=False).st_mtime_ns
                    except OSError:
                        continue
                    seen.add(key)
                    if not full and known.get(key) == mtime:
                        continue
                    changed += self._sync_owner(collection, entry.name, Path(entry.path))
                    db.execute("INSERT OR REPLACE INTO owners VALUES (?, ?, ?)", (collection, entry.name, mtime))
            for collection, owner in set(known) - seen:
                changed += self._drop(
                    [r["ref"] for r in db.execute(
                        "SELECT ref FROM items WHERE collection = ? AND owner = ?", (collection, owner))]
                )
                db.execute("DELETE FROM owners WHERE collection = ? AND owner = ?", (collection, owner))
            db.commit()
            if full:
                self._last_full = started
            self.synced_at = time.time()
            return {"full": full, "changed": changed, "seconds": round(self.synced_at - started, 3)}

    def _sync_owner(self, collection: str, owner: str, owner_dir: Path) -> int:
        db = self._db
        stored = {
            r["ref"]: (r["manifest_mtime"], r["manifest_size"])
            for r in db.execute("SELECT ref, manifest_mtime, manifest_size FROM items WHERE collection = ? AND owner = ?",
                                (collection, owner))
        }
        present: set[str] = set()
        changed = 0
        for child in self.node.item_entries(owner_dir):
            ref = f"{collection}:{owner}/{child.name}"
            item_dir = Path(child.path)
            try:
                st = self.node.manifest_path(item_dir).stat()
            except OSError:
                continue                      # not complete (or gone): not an item
            if stored.get(ref) == (st.st_mtime_ns, st.st_size):
                present.add(ref)
                continue
            entry = self.node._entry(collection, owner, item_dir)
            if entry is None:
                continue
            present.add(ref)
            self._put(entry, item_dir, st.st_mtime_ns, st.st_size)
            changed += 1
        changed += self._drop(sorted(set(stored) - present))
        return changed

    def _put(self, entry: dict, item_dir: Path, mtime: int, size: int) -> None:
        manifest = entry.get("manifest") or {}
        files = [f for f in manifest.get("files", []) if isinstance(f, dict)]
        meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
        derived = [str(r) for r in manifest.get("derived_from", []) if isinstance(r, str)]
        producer = manifest.get("producer") if isinstance(manifest.get("producer"), dict) else {}
        primary = str(manifest.get("primary") or "")
        preview = ""
        if self.node.thumbnail_file(item_dir, manifest) is not None:
            preview = "thumbnail"
        elif primary.lower().endswith(PREVIEW_EXTS):
            size_of = next((int(f.get("bytes") or 0) for f in files if f.get("path") == primary), 0)
            preview = "primary" if 0 < size_of <= PREVIEW_PRIMARY_MAX else ""
        # meta values only: keys such as "Collection" would make every word match.
        search = " ".join(
            [entry["title"], entry["id"], entry["kind"], entry["owner"], str(manifest.get("source") or ""),
             entry["home"], *(str(v) for v in meta.values())]
        ).lower()
        row = (
            entry["ref"], entry["collection"], entry["owner"], entry["id"], entry["kind"], entry["title"],
            entry["created_at"], int(entry["bytes"]), len(files), 1 if entry["replica"] else 0, entry["home"],
            entry["fetched_at"], primary, preview, str(manifest.get("source") or ""),
            str(producer.get("app") or ""), json.dumps(meta, ensure_ascii=False, sort_keys=True),
            json.dumps(derived), search, mtime, size,
        )
        self._db.execute(f"INSERT OR REPLACE INTO items ({', '.join(_COLUMNS)}, search, manifest_mtime, manifest_size) "
                         f"VALUES ({', '.join('?' * (len(_COLUMNS) + 3))})", row)
        self._db.execute("DELETE FROM lineage WHERE ref = ?", (entry["ref"],))
        self._db.executemany("INSERT OR IGNORE INTO lineage VALUES (?, ?)", [(entry["ref"], p) for p in derived])

    def _drop(self, refs: list[str]) -> int:
        for ref in refs:
            self._db.execute("DELETE FROM items WHERE ref = ?", (ref,))
            self._db.execute("DELETE FROM lineage WHERE ref = ?", (ref,))
        return len(refs)

    def forget(self, ref: str) -> None:
        """Drop one item right away (it was deleted through the node)."""
        with self._lock:
            self._drop([ref])
            self._db.commit()

    # -- reading -------------------------------------------------------------------

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {
            "ref": r["ref"], "collection": r["collection"], "owner": r["owner"], "id": r["id"],
            "kind": r["kind"], "title": r["title"], "created_at": r["created_at"], "bytes": r["bytes"],
            "files": r["files"], "local": True, "replica": bool(r["replica"]), "home": r["home"],
            "fetched_at": r["fetched_at"], "primary": r["primary_file"], "preview": r["preview"],
            "source": r["source"], "producer": r["producer"], "meta": json.loads(r["meta"] or "{}"),
            "derived_from": json.loads(r["derived_from"] or "[]"),
        }

    def query(
        self,
        *,
        collection: str | None = None,
        kind: str | None = None,
        owner: str | None = None,
        q: str | None = None,
        location: str | None = None,
        sort: str = "newest",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Items matching every filter given, and how many match in all.

        ``location`` "own" keeps items whose home is this host, "replica" the
        copies fetched from other hosts.  ``q`` matches every word in the title,
        id, kind, owner, source, home or a ``meta`` value.
        """
        where, args = [], []
        for column, value in (("collection", collection), ("kind", kind), ("owner", owner)):
            if value:
                where.append(f"{column} = ?")
                args.append(value)
        if location == "own":
            where.append("replica = 0")
        elif location == "replica":
            where.append("replica = 1")
        for word in (q or "").lower().split():
            where.append("search LIKE ? ESCAPE '\\'")
            args.append(_like(word))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        order = SORTS.get(sort, SORTS["newest"])
        with self._lock:
            total = self._db.execute(f"SELECT COUNT(*) FROM items {clause}", args).fetchone()[0]
            rows = self._db.execute(
                f"SELECT * FROM items {clause} ORDER BY {order} LIMIT ? OFFSET ?", [*args, int(limit), int(offset)]
            ).fetchall()
        return [self._row(r) for r in rows], int(total)

    def get(self, ref: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM items WHERE ref = ?", (ref,)).fetchone()
        return self._row(r) if r else None

    def derived_into(self, ref: str) -> list[dict]:
        """The local items whose ``derived_from`` names ``ref``."""
        with self._lock:
            rows = self._db.execute(
                "SELECT items.* FROM lineage JOIN items ON items.ref = lineage.ref WHERE lineage.parent = ? "
                "ORDER BY items.created_at DESC", (ref,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def facets(self) -> dict:
        """What the filters can choose from, with counts."""
        with self._lock:
            def counts(column: str) -> list[dict]:
                return [{"value": r[0], "items": r[1]} for r in self._db.execute(
                    f"SELECT {column}, COUNT(*) FROM items GROUP BY {column} ORDER BY {column}")]
            return {"collections": counts("collection"), "kinds": counts("kind"), "owners": counts("owner")}

    def usage(self) -> dict[tuple[str, str], dict]:
        """``(collection, owner)`` → items, bytes, replicas, replica_bytes (from the manifests)."""
        out: dict[tuple[str, str], dict] = {}
        with self._lock:
            rows = self._db.execute(
                "SELECT collection, owner, replica, COUNT(*), SUM(bytes) FROM items GROUP BY collection, owner, replica"
            ).fetchall()
        for collection, owner, replica, count, total in rows:
            u = out.setdefault((collection, owner), {"items": 0, "bytes": 0, "replicas": 0, "replica_bytes": 0})
            if replica:
                u["replicas"], u["replica_bytes"] = int(count), int(total or 0)
            else:
                u["items"], u["bytes"] = int(count), int(total or 0)
        return out

    def used_bytes(self, collection: str, owner: str) -> int:
        """Bytes of the items ``owner`` published here (replicas and staging not counted)."""
        with self._lock:
            r = self._db.execute(
                "SELECT SUM(bytes) FROM items WHERE collection = ? AND owner = ? AND replica = 0", (collection, owner)
            ).fetchone()
        return int(r[0] or 0)
