"""pkg-cache: a pull-through download cache for re-ddns app installs.

Every App Store install starts a fresh smart-launcher container, which
downloads the same things again and again: apt .debs, PyPI wheels, npm
tarballs, Node.js / bun / Playwright builds.  This server sits between the app
containers and those upstreams.  Each route maps a URL prefix to one upstream:

    /pypi/simple/<project>/    https://pypi.org/simple/<project>/   (index)
    /pypi/files/<path>         https://files.pythonhosted.org/<path>
    /npm/<package>[/-/<tgz>]   https://registry.npmjs.org/...
    /apt/<host>/<path>         https://<host>/<path>   (Debian, Ubuntu, NodeSource)
    /nodejs/<path>             https://nodejs.org/<path>
    /github/<owner>/<repo>/releases/download/<tag>/<file>   GitHub release assets
    /playwright/<path>         Playwright's browser CDN

Responses come in two kinds:

* Files whose URL names one exact version (a wheel, a .deb in pool/, an npm
  .tgz, node-v22.22.0-linux-arm64.tar.gz, ...) never change, so they are kept
  forever under ``files/<route>/<upstream path>`` and every later request is
  served from disk.  A file is reused only for the very same URL, so another
  version is always a new download.
* Indexes (PyPI simple pages, npm package documents, apt InRelease, Node.js
  ``latest-*`` listings) change when something is published, so they are kept
  under ``meta/`` but re-checked upstream once older than PKG_CACHE_META_TTL
  seconds (a conditional request, usually a cheap 304).  Version resolution
  therefore sees what it would see without the cache.  When the upstream cannot
  be reached, the last copy is served, so versions installed before can be
  installed again offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from aiohttp import ClientSession, ClientTimeout, TCPConnector, web

log = logging.getLogger("pkg-cache")

DATA = Path(os.environ.get("PKG_CACHE_DIR", "/data"))
PORT = int(os.environ.get("PKG_CACHE_PORT", "3142"))
META_TTL = int(os.environ.get("PKG_CACHE_META_TTL", "300"))
APT_HOSTS = set(os.environ.get(
    "PKG_CACHE_APT_HOSTS",
    "deb.debian.org security.debian.org deb.nodesource.com "
    "archive.ubuntu.com ports.ubuntu.com security.ubuntu.com",
).split())

# Upstreams (overridable, e.g. to use a regional mirror).
PYPI = os.environ.get("PKG_CACHE_PYPI_URL", "https://pypi.org").rstrip("/")
PYPI_FILES = os.environ.get("PKG_CACHE_PYPI_FILES_URL", "https://files.pythonhosted.org").rstrip("/")
NPM = os.environ.get("PKG_CACHE_NPM_URL", "https://registry.npmjs.org").rstrip("/")
NODEJS = os.environ.get("PKG_CACHE_NODEJS_URL", "https://nodejs.org").rstrip("/")
GITHUB = os.environ.get("PKG_CACHE_GITHUB_URL", "https://github.com").rstrip("/")
PLAYWRIGHT = os.environ.get(
    "PKG_CACHE_PLAYWRIGHT_URL", "https://cdn.playwright.dev/dbazure/download/playwright"
).rstrip("/")

FILES = DATA / "files"
META = DATA / "meta"
TMP = DATA / "tmp"
STATS_PATH = DATA / "stats.json"

CHUNK = 256 * 1024
USER_AGENT = "re-ddns-pkg-cache/1.0"
# connect=None: waiting for a free pooled connection must not time out while
# other downloads hold them; sock_connect bounds the actual TCP connect.
FILE_TIMEOUT = ClientTimeout(total=None, connect=None, sock_connect=20, sock_read=120)
META_TIMEOUT = ClientTimeout(total=180, connect=None, sock_connect=20, sock_read=60)


# ---------------------------------------------------------------------------
# Routes: URL tail -> what to fetch and how to keep it
# ---------------------------------------------------------------------------

@dataclass
class Target:
    route: str                  # first URL segment: pypi, npm, apt, ...
    key: list[str]              # storage path below files/<route> or meta/<route>
    url: str                    # upstream URL
    kind: str                   # "file" (kept forever) or "meta" (revalidated)
    variant: str = "default"    # meta: which representation (e.g. npm abbreviated)
    accept: str = ""            # meta: Accept header sent upstream
    ttl: int = META_TTL         # meta: seconds a copy is used without asking upstream
    # meta: (upstream prefix, our path) pairs rewritten so that the files an
    # index points to are fetched through the cache too
    rewrite: tuple[tuple[bytes, str], ...] = ()
    digest: tuple[str, str] | None = None   # file: (hashlib name, hex) its URL promises


class Unsupported(Exception):
    """The URL is not one this cache knows how to keep."""


def _q(segs: list[str]) -> str:
    return "/".join(quote(s, safe="@+:=,!~*'()$&;") for s in segs)


PYPI_JSON = "application/vnd.pypi.simple.v1+json"


def resolve_pypi(segs: list[str], slash: bool, accept: str) -> Target:
    rewrite = ((f"{PYPI_FILES}/".encode(), "/pypi/files/"),)
    head, rest = segs[0], segs[1:]
    if head == "simple" and len(rest) <= 1:
        # PEP 691 JSON or the classic HTML page, whichever the client asked for.
        json_page = PYPI_JSON in accept
        return Target(
            "pypi", ["simple", *rest], f"{PYPI}/simple/{_q(rest)}{'/' if rest else ''}", "meta",
            variant="json" if json_page else "html",
            accept=PYPI_JSON if json_page else "text/html",
            rewrite=rewrite,
        )
    if head == "pypi" and rest and rest[-1] == "json":   # JSON API
        return Target("pypi", segs, f"{PYPI}/{_q(segs)}", "meta",
                      accept="application/json", rewrite=rewrite)
    if head == "files" and rest and not slash:
        digest = None
        # packages/ab/cd/<60 hex>/<file>: the three dirs are the file's BLAKE2b-256.
        if len(rest) == 5 and rest[0] == "packages" and not rest[4].endswith(".metadata"):
            hexdigest = "".join(rest[1:4])
            if re.fullmatch(r"[0-9a-f]{64}", hexdigest):
                digest = ("blake2b", hexdigest)
        return Target("pypi", rest, f"{PYPI_FILES}/{_q(rest)}", "file", digest=digest)
    raise Unsupported


def _case_safe(seg: str) -> str:
    # The data folder lives on the Mac, whose file system ignores case, but
    # npm has old package names that differ only in case (JSONStream vs
    # jsonstream).  Store "A" as "!a" (and "!" as "!!"), like Go's module cache.
    return "".join("!" + c.lower() if c.isupper() else "!!" if c == "!" else c for c in seg)


def resolve_npm(segs: list[str], slash: bool, accept: str) -> Target:
    n = 2 if segs[0].startswith("@") else 1
    if len(segs) < n or segs[0] == "-":
        raise Unsupported
    name, rest = segs[:n], segs[n:]
    key = [_case_safe(s) for s in segs]
    rewrite = ((f"{NPM}/".encode(), "/npm/"),)
    if not rest:
        # Package document: the abbreviated one installers ask for, or the full one.
        abbreviated = "application/vnd.npm.install-v1+json" in accept
        return Target(
            "npm", key, f"{NPM}/{quote('/'.join(name), safe='@')}", "meta",
            variant="abbreviated" if abbreviated else "full",
            accept=("application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8"
                    if abbreviated else "application/json"),
            rewrite=rewrite,
        )
    if len(rest) == 2 and rest[0] == "-" and rest[1].endswith(".tgz") and not slash:
        return Target("npm", key, f"{NPM}/{_q(segs)}", "file")
    if len(rest) == 1:   # one version's document, e.g. /react/19.0.0 or /react/latest
        return Target("npm", key, f"{NPM}/{_q(segs)}", "meta",
                      accept="application/json", rewrite=rewrite)
    raise Unsupported


def resolve_apt(segs: list[str], slash: bool, accept: str) -> Target:
    host, path = segs[0], segs[1:]
    if host not in APT_HOSTS or not path or slash:
        raise Unsupported
    url = f"https://{host}/{_q(path)}"
    # pool/ holds the .debs, by-hash/ the indexes under their own checksum:
    # neither ever changes.  Everything else in dists/ moves with each update.
    if "pool" in path or "by-hash" in path:
        digest = None
        if len(path) >= 2 and path[-2] == "SHA256" and re.fullmatch(r"[0-9a-f]{64}", path[-1]):
            digest = ("sha256", path[-1])
        return Target("apt", segs, url, "file", digest=digest)
    # InRelease lists the checksums of the index files fetched right after it,
    # so always ask upstream whether it changed (a cheap conditional request).
    return Target("apt", segs, url, "meta", ttl=0)


def resolve_nodejs(segs: list[str], slash: bool, accept: str) -> Target:
    if segs[0] not in ("dist", "download"):
        raise Unsupported
    url = f"{NODEJS}/{_q(segs)}{'/' if slash else ''}"
    # dist/v22.22.0/<file> and download/release/v22.22.0/<file> never change;
    # latest-v22.x/, index.json and directory listings do.
    version_dir = segs[1] if segs[0] == "dist" else (segs[2] if len(segs) > 2 else "")
    depth = 3 if segs[0] == "dist" else 4
    if len(segs) == depth and re.fullmatch(r"v\d+\.\d+\.\d+", version_dir) and not slash:
        return Target("nodejs", segs, url, "file")
    return Target("nodejs", segs, url, "meta")


def resolve_github(segs: list[str], slash: bool, accept: str) -> Target:
    # <owner>/<repo>/releases/download/<tag>/<file>: bun, uv's Python builds,
    # livekit-server ...  ("releases/latest/download" moves, so it is not kept.)
    if len(segs) == 6 and segs[2:4] == ["releases", "download"] and not slash:
        return Target("github", segs, f"{GITHUB}/{_q(segs)}", "file")
    raise Unsupported


def resolve_playwright(segs: list[str], slash: bool, accept: str) -> Target:
    # builds/<browser>/<revision>/<file>
    if segs[0] == "builds" and len(segs) >= 4 and not slash:
        return Target("playwright", segs, f"{PLAYWRIGHT}/{_q(segs)}", "file")
    raise Unsupported


RESOLVERS = {
    "pypi": resolve_pypi,
    "npm": resolve_npm,
    "apt": resolve_apt,
    "nodejs": resolve_nodejs,
    "github": resolve_github,
    "playwright": resolve_playwright,
}


def split_tail(raw_tail: str) -> tuple[list[str], bool] | None:
    """Decode a raw URL path tail into safe segments (None if unsafe).

    Percent-escapes are decoded first, so npm's "@scope%2fname" and
    "@scope/name" become the same two segments.
    """
    tail = unquote(raw_tail)
    slash = tail.endswith("/")
    segs = tail.rstrip("/").split("/")
    for s in segs:
        if s in ("", ".", "..") or "\x00" in s or "\\" in s or "#" in s or len(s.encode()) > 240:
            return None
    return segs, slash


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

COUNTERS = ("hit", "miss", "revalidated", "stale", "error", "bytes_cached", "bytes_upstream")


def _empty() -> dict[str, int]:
    return dict.fromkeys(COUNTERS, 0)


STATS: dict[str, dict[str, int]] = {r: _empty() for r in RESOLVERS}
_recent: dict[str, int] = _empty()      # since the last summary log line
_stats_dirty = False


def count(route: str, counter: str, n: int = 1) -> None:
    global _stats_dirty
    STATS.setdefault(route, _empty())[counter] += n
    _recent[counter] += n
    _stats_dirty = True


def load_stats() -> None:
    try:
        saved = json.loads(STATS_PATH.read_text())
    except (OSError, ValueError):
        return
    for route, counters in saved.items():
        for k in COUNTERS:
            STATS.setdefault(route, _empty())[k] = int(counters.get(k, 0))


def save_stats() -> None:
    global _stats_dirty
    if not _stats_dirty:
        return
    tmp = STATS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(STATS, indent=1))
    os.replace(tmp, STATS_PATH)
    _stats_dirty = False


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


async def housekeeping(app: web.Application) -> None:
    """Every minute: persist the counters and log what happened."""
    while True:
        await asyncio.sleep(60)
        try:
            save_stats()
        except OSError as exc:
            log.warning("could not save stats: %s", exc)
        r = dict(_recent)
        if r["hit"] or r["miss"] or r["stale"] or r["error"]:
            log.info("last minute: %d hits (%s from disk), %d downloads (%s from upstream), "
                     "%d revalidated, %d stale, %d errors",
                     r["hit"], _mb(r["bytes_cached"]), r["miss"], _mb(r["bytes_upstream"]),
                     r["revalidated"], r["stale"], r["error"])
        for k in _recent:
            _recent[k] = 0


# ---------------------------------------------------------------------------
# Upstream sessions
# ---------------------------------------------------------------------------

def _session(decompress: bool) -> ClientSession:
    return ClientSession(
        connector=TCPConnector(limit=64, limit_per_host=16, ttl_dns_cache=300),
        headers={"User-Agent": USER_AGENT},
        auto_decompress=decompress,
    )


async def on_startup(app: web.Application) -> None:
    for d in (FILES, META, TMP):
        d.mkdir(parents=True, exist_ok=True)
    for leftover in TMP.iterdir():   # downloads cut short by the last shutdown
        if leftover.is_file():
            leftover.unlink(missing_ok=True)
    load_stats()
    # Files are stored byte for byte, so nothing may undo a Content-Encoding;
    # index bodies are decoded because their URLs get rewritten.
    app["files"] = _session(decompress=False)
    app["meta"] = _session(decompress=True)
    app["downloads"] = set()   # running download() tasks (asyncio keeps only weak refs)
    app["housekeeping"] = asyncio.create_task(housekeeping(app))


async def on_cleanup(app: web.Application) -> None:
    app["housekeeping"].cancel()
    await app["files"].close()
    await app["meta"].close()
    save_stats()


# ---------------------------------------------------------------------------
# Files: kept forever, one shared download per file
# ---------------------------------------------------------------------------

@dataclass
class Fetch:
    """One upstream download, streamed to every client that asks meanwhile."""
    target: Target
    final: Path
    tmp: Path = field(default_factory=lambda: TMP / uuid.uuid4().hex)
    status: int = 0
    content_type: str = "application/octet-stream"
    total: int | None = None
    size: int = 0
    done: bool = False
    failed: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)
    progress: asyncio.Event = field(default_factory=asyncio.Event)

    def notify(self) -> None:
        event, self.progress = self.progress, asyncio.Event()
        event.set()


INFLIGHT: dict[Path, Fetch] = {}


def _hasher(digest: tuple[str, str] | None):
    if digest is None:
        return None
    if digest[0] == "blake2b":
        return hashlib.blake2b(digest_size=32)   # PyPI's 256-bit variant
    return hashlib.new(digest[0])


async def download(app: web.Application, fetch: Fetch) -> None:
    t = fetch.target
    try:
        async with app["files"].get(t.url, headers={"Accept-Encoding": "identity"},
                                    timeout=FILE_TIMEOUT) as up:
            fetch.status = up.status
            if up.status != 200:
                log.info("%s %d upstream: %s", t.route, up.status, t.url)
                return
            fetch.total = up.content_length
            fetch.content_type = up.headers.get("Content-Type", fetch.content_type)
            hasher = _hasher(t.digest)
            with open(fetch.tmp, "wb") as fh:
                fetch.started.set()
                async for chunk in up.content.iter_chunked(CHUNK):
                    fh.write(chunk)
                    fh.flush()   # readers follow the file while it grows
                    if hasher:
                        hasher.update(chunk)
                    fetch.size += len(chunk)
                    fetch.notify()
        if fetch.total is not None and fetch.size != fetch.total:
            raise OSError(f"got {fetch.size} of {fetch.total} bytes")
        if hasher and hasher.hexdigest() != t.digest[1]:
            raise OSError(f"{t.digest[0]} mismatch (got {hasher.hexdigest()})")
        fetch.final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(fetch.tmp, fetch.final)
        fetch.done = True
        count(t.route, "bytes_upstream", fetch.size)
        log.info("%s MISS %s (%s)", t.route, "/".join(t.key), _mb(fetch.size))
    except Exception as exc:  # noqa: BLE001 - any failure: drop the partial file
        fetch.failed = True
        count(t.route, "error")
        log.warning("%s download failed: %s: %s", t.route, t.url, exc or type(exc).__name__)
        fetch.tmp.unlink(missing_ok=True)
    finally:
        INFLIGHT.pop(fetch.final, None)
        fetch.started.set()
        fetch.notify()


def _cut(request: web.Request, resp: web.StreamResponse) -> web.StreamResponse:
    """Close the connection mid-body: the client sees a short download and
    retries, instead of keeping a broken file."""
    resp.force_close()
    if request.transport is not None:
        request.transport.close()
    return resp


async def serve_file(request: web.Request, t: Target) -> web.StreamResponse:
    final = FILES.joinpath(t.route, *t.key)
    if final.is_file():
        count(t.route, "hit")
        if request.method == "GET":
            count(t.route, "bytes_cached", final.stat().st_size)
        # A preset Content-Type also stops aiohttp from adding
        # "Content-Encoding: gzip" for .tgz / .tar.gz, which clients would undo.
        ctype, encoding = mimetypes.guess_type(final.name)
        if encoding or not ctype:
            ctype = "application/octet-stream"
        # FileResponse also answers HEAD and Range requests.
        return web.FileResponse(final, headers={"Content-Type": ctype, "X-Cache": "HIT"})
    if request.method == "HEAD":
        return await passthrough(request, t.url)

    fetch = INFLIGHT.get(final)
    if fetch is None:
        fetch = INFLIGHT[final] = Fetch(t, final)
        count(t.route, "miss")
        # Not tied to this request: the file is kept even if the client leaves.
        downloads = request.app["downloads"]
        task = asyncio.create_task(download(request.app, fetch))
        downloads.add(task)
        task.add_done_callback(downloads.discard)
    await fetch.started.wait()
    if fetch.status != 200:
        return web.Response(status=fetch.status or 502,
                            text=f"pkg-cache: upstream answered {fetch.status or 'nothing'} for {t.url}\n")
    try:
        fh = open(fetch.tmp, "rb", buffering=0)
    except FileNotFoundError:   # finished (and moved into place) or failed already
        if not fetch.done:
            return web.Response(status=502, text=f"pkg-cache: download failed: {t.url}\n")
        fh = open(fetch.final, "rb", buffering=0)

    resp = web.StreamResponse(headers={"Content-Type": fetch.content_type, "X-Cache": "MISS"})
    if fetch.total is not None:
        resp.content_length = fetch.total
    await resp.prepare(request)
    sent = idle = 0
    with fh:
        # Follow the file while download() appends to it.
        while True:
            event = fetch.progress
            chunk = fh.read(min(CHUNK, fetch.size - sent)) if sent < fetch.size else b""
            if chunk:
                await resp.write(chunk)
                sent += len(chunk)
                idle = 0
                continue
            if fetch.done and sent >= fetch.size:
                break
            if fetch.failed or idle > 200:
                return _cut(request, resp)
            if sent < fetch.size:   # written but not readable yet: look again shortly
                idle += 1
                await asyncio.sleep(0.05)
            else:
                await event.wait()
    await resp.write_eof()
    return resp


async def passthrough(request: web.Request, url: str) -> web.StreamResponse:
    """Relay one request without keeping anything."""
    session = request.app["files"]
    async with session.request(request.method, url, timeout=FILE_TIMEOUT) as up:
        headers = {h: up.headers[h] for h in ("Content-Type", "Content-Length", "Content-Encoding",
                                              "Last-Modified", "ETag") if h in up.headers}
        resp = web.StreamResponse(status=up.status, headers={**headers, "X-Cache": "PASS"})
        await resp.prepare(request)
        if request.method != "HEAD":
            async for chunk in up.content.iter_chunked(CHUNK):
                await resp.write(chunk)
        await resp.write_eof()
        return resp


# ---------------------------------------------------------------------------
# Indexes: kept, but re-checked upstream once older than their TTL
# ---------------------------------------------------------------------------

META_LOCKS: dict[Path, asyncio.Lock] = {}


def _read_info(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = TMP / uuid.uuid4().hex
    tmp.write_bytes(data)
    os.replace(tmp, path)


async def refresh_meta(app: web.Application, t: Target, body_p: Path, info_p: Path,
                       old: dict | None) -> tuple[dict | None, str | int]:
    """Ask upstream for a newer copy.  Returns (info, cache state) or (None, status)."""
    headers = {"Accept": t.accept} if t.accept else {}
    have_body = old is not None and body_p.is_file()
    if have_body:
        if old.get("etag"):
            headers["If-None-Match"] = old["etag"]
        if old.get("last_modified"):
            headers["If-Modified-Since"] = old["last_modified"]
    try:
        async with app["meta"].get(t.url, headers=headers, timeout=META_TIMEOUT) as up:
            if up.status == 304 and have_body:
                old["fetched"] = time.time()
                _write_atomic(info_p, json.dumps(old).encode())
                count(t.route, "revalidated")
                return old, "REVALIDATED"
            if up.status == 200:
                body = await up.read()
                info = {
                    "url": t.url,
                    "content_type": up.headers.get("Content-Type", "application/octet-stream"),
                    "etag": up.headers.get("ETag", ""),
                    "last_modified": up.headers.get("Last-Modified", ""),
                    "fetched": time.time(),
                }
                _write_atomic(body_p, body)
                _write_atomic(info_p, json.dumps(info).encode())
                count(t.route, "miss")
                count(t.route, "bytes_upstream", len(body))
                return info, "MISS"
            if 400 <= up.status < 500 and up.status not in (408, 429):
                return None, up.status   # e.g. no such package: upstream knows best
            raise OSError(f"upstream answered {up.status}")
    except Exception as exc:  # noqa: BLE001 - offline, timeout, 5xx ...
        if have_body:
            count(t.route, "stale")
            log.warning("%s upstream unavailable (%s), serving the last copy of %s",
                        t.route, exc or type(exc).__name__, t.url)
            return old, "STALE"
        count(t.route, "error")
        log.warning("%s upstream unavailable (%s) and nothing cached: %s",
                    t.route, exc or type(exc).__name__, t.url)
        return None, 502


async def serve_meta(request: web.Request, t: Target) -> web.Response:
    base = META.joinpath(t.route, *t.key)
    body_p, info_p = base / f"#{t.variant}", base / f"#{t.variant}.json"

    def fresh(info: dict | None) -> bool:
        return bool(info) and body_p.is_file() and time.time() - info.get("fetched", 0) < t.ttl

    info, state = _read_info(info_p), "HIT"
    if not fresh(info):
        lock = META_LOCKS.setdefault(body_p, asyncio.Lock())
        async with lock:
            info = _read_info(info_p)   # another request may have refreshed it meanwhile
            if not fresh(info):
                info, state = await refresh_meta(request.app, t, body_p, info_p, info)
        if not lock.locked():
            META_LOCKS.pop(body_p, None)
    if info is None:
        return web.Response(status=int(state), text=f"pkg-cache: upstream answered {state} for {t.url}\n")
    if state == "HIT":
        count(t.route, "hit")
    body = body_p.read_bytes()
    origin = f"{request.scheme}://{request.host}"
    for upstream_prefix, our_path in t.rewrite:
        body = body.replace(upstream_prefix, f"{origin}{our_path}".encode())
    return web.Response(body=body, headers={"Content-Type": info["content_type"], "X-Cache": state})


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def proxy(request: web.Request) -> web.StreamResponse:
    route = request.match_info["route"]
    if request.method not in ("GET", "HEAD"):
        return web.Response(status=405, text="pkg-cache only serves GET and HEAD\n")
    prefix = f"/{route}/"
    raw = request.rel_url.raw_path
    parsed = split_tail(raw[len(prefix):]) if raw.startswith(prefix) else None
    try:
        if parsed is None or request.rel_url.raw_query_string:
            raise Unsupported
        target = RESOLVERS[route](parsed[0], parsed[1], request.headers.get("Accept", ""))
    except Unsupported:
        return web.Response(status=404, text=f"pkg-cache: no {route} route for {raw}\n")
    if target.kind == "file":
        return await serve_file(request, target)
    return await serve_meta(request, target)


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


_usage_cache: dict = {}


def _disk_usage() -> dict[str, dict[str, int]]:
    usage = {}
    for route in RESOLVERS:
        files = size = 0
        for root, kept_files in ((FILES / route, True), (META / route, False)):
            for dirpath, _dirs, names in os.walk(root):
                for n in names:
                    try:
                        size += os.stat(os.path.join(dirpath, n)).st_size
                    except OSError:
                        continue
                    files += kept_files
        usage[route] = {"files": files, "bytes": size}
    return usage


async def disk_usage() -> dict[str, dict[str, int]]:
    if time.time() - _usage_cache.get("at", 0) > 60:
        _usage_cache["usage"] = await asyncio.to_thread(_disk_usage)
        _usage_cache["at"] = time.time()
    return _usage_cache["usage"]


async def status_json(request: web.Request) -> web.Response:
    return web.json_response({"stats": STATS, "disk": await disk_usage(),
                              "in_progress": [str(p.relative_to(FILES)) for p in INFLIGHT]})


async def status_page(request: web.Request) -> web.Response:
    disk = await disk_usage()
    rows = "".join(
        f"<tr><td>{r}</td><td>{disk[r]['files']}</td><td>{_mb(disk[r]['bytes'])}</td>"
        f"<td>{s['hit']}</td><td>{s['miss']}</td><td>{s['stale']}</td>"
        f"<td>{_mb(s['bytes_cached'])}</td><td>{_mb(s['bytes_upstream'])}</td></tr>"
        for r, s in STATS.items() if r in disk
    )
    base = html.escape(f"{request.scheme}://{request.host}")
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>pkg-cache</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e5e5ea}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1c1e;--fg:#f5f5f7;--muted:#a1a1a6;--line:#3a3a3c}}}}
body{{margin:0 auto;max-width:860px;padding:24px 16px;font:14px/1.5 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}}
th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-weight:500}}
code{{font-size:13px}}p{{color:var(--muted)}}.wrap{{overflow-x:auto}}
</style></head><body>
<h1>pkg-cache</h1>
<p>Downloads made by app installs. A file whose URL names one exact version is kept and served
from disk; indexes are re-checked upstream every {META_TTL} s. Counters are cumulative.</p>
<div class="wrap"><table><tr><th>Route</th><th>Files</th><th>On disk</th><th>Hits</th><th>Downloads</th>
<th>Stale</th><th>Served from disk</th><th>Fetched upstream</th></tr>{rows}</table></div>
<p>Base URL for clients: <code>{base}</code> &middot; <a href="/_status">JSON</a></p>
</body></html>"""
    return web.Response(text=page, content_type="text/html")


def make_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", status_page)
    app.router.add_get("/_health", health)
    app.router.add_get("/_status", status_json)
    app.router.add_route("*", "/{route:" + "|".join(RESOLVERS) + "}/{tail:.*}", proxy)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("PKG_CACHE_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    log.info("pkg-cache on :%d, data in %s, indexes re-checked after %d s", PORT, DATA, META_TTL)
    web.run_app(make_app(), port=PORT, access_log=None, print=None)
