# pkg-cache — design

中文版：[DESIGN_ZH.md](DESIGN_ZH.md) · Running and checking it: [README.md](README.md)

## At a glance

```
 app installs                         cache                                  internet
┌──────────────────────────┐         ┌────────────────────────────┐         ┌────────────────────────┐
│ smart-app-* containers   │  HTTP   │ pkg-cache  :3142           │  HTTPS  │ pypi.org               │
│                          │────────►│ same file before? → disk   │────────►│ registry.npmjs.org     │
│ apt, Poetry, pip, uv,    │         │ new file → download once   │  only   │ deb.debian.org         │
│ bun, Node.js, Playwright │         │ index → re-check (5 min)   │  when   │ nodejs.org, github.com │
└──────────────────────────┘         └──────────────┬─────────────┘  needed └────────────────────────┘
                                                    │ /data
                                     ┌──────────────▼─────────────┐
                                     │ pkg_cache/data/ on the Mac │
                                     │ (git-ignored)              │
                                     └────────────────────────────┘
```

- **What:** one container, `pkg-cache`, that app installs download through.
- **The rule:** a file whose URL names one exact version (a wheel, an npm `.tgz`, a `.deb`, a
  Node.js build) is downloaded once and served from disk after that. Another version has
  another URL, so it is always a new download.
- **Indexes stay current:** the lists of available versions (PyPI pages, npm package
  documents, apt `InRelease`) are re-checked upstream after 5 minutes, so installs pick the
  same versions they would pick without the cache.
- **Where the files are:** `pkg_cache/data/` on the Mac, git-ignored.
- **Optional:** when the cache is not running, apps download directly, as before.
- **Effect:** reinstalling ReflexGrid in a fresh container went from 333 s and 168 MB
  downloaded to 83 s with no packages downloaded.

## 1. Why

Every App Store install starts a fresh smart-launcher container, and its entrypoint downloads
all dependencies again:

| Download | Tool | Size (measured) |
|----------|------|-----------------|
| apt indexes + packages (`ffmpeg`, Noto fonts, …) | apt-get | 9 MB of indexes per `apt-get update`, plus the packages |
| Python wheels | Poetry, pip, uv | 73 MB for ReflexGrid; the running apps' Poetry caches hold 125–180 MB each |
| Frontend packages | bun, through Reflex | 38 MB of tarballs for ReflexGrid; 180–375 MB unpacked per running app |
| Node.js 22 (Reflex 0.10 apps) | the launcher | 57 MB |
| Chromium (Playwright apps) | Playwright | 111 MB |

The same files come back across apps (every Reflex app pulls Reflex, FastAPI, React, Vite,
Radix …) and across reinstalls (`docker_restart.sh` removes every smart-app container). On a
phone hotspot (0.3–1 MB/s) that costs minutes per install.

**Goals**

1. Download each exact file once; serve it from local disk after that.
2. Never hand out a version other than the one asked for.
3. Resolve versions exactly as without the cache.
4. Keep working offline for everything downloaded before.
5. No changes in the apps, and optional: installs fall back to direct downloads.
6. Small: the Docker VM's memory is tight (it has run out before).

**Not goals:** a general web proxy; caching what apps download while they run; private
packages or publishing; automatic eviction.

## 2. Components

| Piece | Where | Role |
|-------|-------|------|
| Cache server | [server.py](server.py) (one file, aiohttp), [Dockerfile](Dockerfile) | Maps URL prefixes to upstreams; keeps files; re-checks indexes |
| Storage | `pkg_cache/data/` on the host = `/data` in the container | Kept files, indexes, counters |
| Client setup | [smart_launcher/entrypoint.sh](../smart_launcher/entrypoint.sh), section 0.5 | Finds the cache at start and points each tool at it |
| Service | `pkg-cache` in [docker-compose.test.yml](../docker-compose.test.yml); [docker_restart.sh](../docker_restart.sh) step 2.6 | Runs it on `ddns-net` and on `127.0.0.1:3142` |

## 3. The core rule: files and indexes

A package manager works in two steps: it reads an **index** to choose a version, then
downloads that version's **file**. The cache treats the two differently:

| | File | Index |
|-|------|-------|
| Examples | `six-1.17.0-py2.py3-none-any.whl`, `react-19.0.0.tgz`, `pool/…/jq_1.6-2.1+deb12u2_arm64.deb`, `dist/v22.23.3/node-v22.23.3-linux-arm64.tar.gz` | `/simple/six/`, npm's document for `react`, apt's `InRelease`, `latest-v22.x/SHASUMS256.txt` |
| Can it change? | No: the URL names one version | Yes, whenever something is published |
| Kept | Forever, under its upstream path | Yes, with its ETag, Last-Modified and fetch time |
| Served from disk | Always, once present | While younger than the TTL (300 s; apt: re-checked every time) |
| Otherwise | Downloaded once, streamed to the client, kept | Conditional request upstream: `304` → reuse, `200` → replace |
| Upstream unreachable | Not needed | The last copy is served (`STALE`) |

**Why "same version only" holds.** The cache key is the file's URL, and the version is part of
that URL. Asking for `react-19.1.0.tgz` when only `react-19.0.0.tgz` is kept is a miss, so the
cache can never hand out a different version. The version itself is chosen by the client
(Poetry, uv, bun, apt) from an index at most 5 minutes old — stricter than PyPI, whose index
pages say `Cache-Control: max-age=600`.

**How the files come through the cache: URL rewriting.** Indexes point at files with absolute
URLs (`https://files.pythonhosted.org/packages/…`,
`https://registry.npmjs.org/react/-/react-19.0.0.tgz`). When serving a PyPI or npm index, the
cache replaces those prefixes with its own address, taken from the request's `Host` header:
`http://pkg-cache:3142/pypi/files/…` inside Docker, `http://localhost:3142/…` on the Mac. The
stored copy keeps the original bytes and the rewrite happens per response, so one copy serves
every client. apt, Node.js and Playwright need no rewriting: they build file URLs from the
base URL they are given.

## 4. Request flow

**File**

```
GET /npm/react/-/react-19.0.0.tgz
 │
 ├─ data/files/npm/react/-/react-19.0.0.tgz exists? ──yes──► send it from disk    HIT
 │                                                           (Range and HEAD work)
 ├─ HEAD request? ──yes──► relay upstream's headers, keep nothing                 PASS
 │
 ├─ this file already downloading? ──yes──► join it, stream bytes as they arrive  MISS
 │
 └─ start one download in the background                                          MISS
      upstream ──► data/tmp/<random> ──► length and hash OK? ──► move into data/files/…
                     │ (clients read this file while it grows)
                     └─ broken or wrong: delete it, cut the clients' connections (they retry)
```

**Index**

```
GET /pypi/simple/six/              (the Accept header picks the JSON or the HTML copy)
 │
 ├─ copy younger than the TTL? ──yes──► send it, file URLs rewritten              HIT
 │
 └─ ask upstream with If-None-Match / If-Modified-Since (one request per index at a time)
      ├─ 304 Not Modified ──────► mark it fresh, send the copy                    REVALIDATED
      ├─ 200 ───────────────────► replace the copy, send it                       MISS
      ├─ 404 and similar ───────► pass the answer on (e.g. no such package)
      └─ timeout, 5xx, offline ─► send the last copy                              STALE
                                  (502 if there is none)
```

The last word on each line is the `X-Cache` response header, which shows how a request was
answered.

## 5. Routes

| Route (`http://pkg-cache:3142…`) | Upstream | Kept as files | Treated as indexes | Used by |
|----------------------------------|----------|---------------|--------------------|---------|
| `/pypi/files/…` | files.pythonhosted.org | all (wheels, sdists, `.metadata`) | — | Poetry, pip, uv |
| `/pypi/simple/<project>/`, `/pypi/pypi/<project>/json` | pypi.org | — | all; JSON and HTML copies kept apart | Poetry, pip, uv |
| `/npm/<pkg>/-/<file>.tgz` | registry.npmjs.org | tarballs | — | bun, npm |
| `/npm/<pkg>` | registry.npmjs.org | — | package documents; abbreviated and full kept apart | bun, npm |
| `/apt/<host>/…` | `https://<host>/…`, allow-listed hosts only | `pool/`, `by-hash/` | the rest of `dists/` | apt-get, `playwright install-deps` |
| `/nodejs/…` | nodejs.org | `dist/v<x.y.z>/<file>` | `latest-*`, `index.json`, listings | the launcher's Node.js download |
| `/github/<owner>/<repo>/releases/download/<tag>/<file>` | github.com (redirects followed) | release assets | — (`releases/latest` is refused) | Reflex's bun installer, uv's Python builds |
| `/playwright/builds/…` | Playwright's CDN | browser builds | — | `playwright install` |

Anything else — other paths, query strings, methods other than GET and HEAD — gets `404` or
`405`. The cache is not a general proxy.

## 6. Storage layout

```
pkg_cache/data/                         (host)  =  /data  (container)
├─ files/<route>/<upstream path>        kept files; never changed once written, e.g.
│    pypi/packages/b7/ce/149a…5e/six-1.17.0-py2.py3-none-any.whl
│    npm/react/-/react-19.0.0.tgz
│    apt/deb.debian.org/debian/pool/main/j/jq/jq_1.6-2.1+deb12u2_arm64.deb
│    nodejs/dist/v22.23.3/node-v22.23.3-linux-arm64.tar.gz
├─ meta/<route>/<path>/#<variant>       an index as fetched, e.g. meta/npm/react/#abbreviated
│                      #<variant>.json  its URL, Content-Type, ETag, Last-Modified, fetch time
├─ tmp/                                 downloads in progress (emptied at start)
└─ stats.json                           the counters shown on the status page
```

- Everything is written to `tmp/` first and moved into place with an atomic rename, so a
  half-written file is never served.
- Paths mirror the upstream URLs, so the folder can be browsed and pruned by hand. Deleting
  anything is safe: it is downloaded again the next time it is needed.
- The folder is on macOS, whose file system ignores case, but npm still has old names that
  differ only in case (`JSONStream` and `jsonstream`). npm paths therefore store an uppercase
  letter as `!` plus the lowercase letter (`!j!s!o!n!stream`), as Go's module cache does.
- Index files are named `#<variant>`. The cache refuses `#` in URL paths, so these names
  cannot clash with package paths.

## 7. Concurrency and integrity

- **One download per file.** A request for a file that is already downloading joins that
  download and streams from the growing temp file. Measured: 3 clients asked for the same
  uncached 2.1 MB wheel at once; it was fetched once, and all three got identical, correct files.
- **Downloads outlive clients.** Each download runs as its own task, so it finishes and is kept
  even when the client that started it disconnects.
- **One check per index.** A lock per index stops a burst of requests from re-checking the
  same index in parallel.
- **Checks before a file is kept.** The byte count must match `Content-Length`. PyPI paths
  (`packages/ab/cd/<60 hex>/…`) contain the file's BLAKE2b-256 and apt `by-hash/SHA256/<hex>`
  paths its SHA-256; both are verified. On any failure nothing is kept and the clients'
  connections are cut, so they see an incomplete download and retry.
- **Clients still verify.** pip, Poetry and uv check the sha256 from the index or lock file;
  bun checks npm's `integrity`; apt checks the hashes in the signed `InRelease`; the launcher
  checks Node.js against `SHASUMS256.txt`.

## 8. How apps use it

Section 0.5 of `smart_launcher/entrypoint.sh` runs on every container start:

1. `PKG_CACHE_URL` defaults to `http://pkg-cache:3142`; an empty value turns the cache off.
2. apt sources rewritten by a previous start are restored (copies kept in
   `/var/lib/smart-launcher/apt-sources-orig`).
3. `$PKG_CACHE_URL/_health` is tried up to 5 times, 1 s apart, because after a Docker restart
   every container starts at the same moment.
4. If the cache answers, the launcher logs `Package cache: …` and sets up each tool:

| Tool | How it is pointed at the cache |
|------|--------------------------------|
| apt | `deb.debian.org`, `security.debian.org` and `deb.nodesource.com` URLs in the sources become `$PKG_CACHE_URL/apt/<host>/`; the originals are saved for step 2 |
| Poetry 1.8 | Poetry reads indexes only from `pyproject.toml` and ignores `PIP_INDEX_URL`. Just before `poetry lock`, `[[tool.poetry.source]] name = "pkg-cache"`, `priority = "primary"` is appended to the container's copy of `pyproject.toml`. A primary source replaces the implicit PyPI: Poetry makes no requests to pypi.org, and the lock records `reference = "pkg-cache"` (verified). Skipped when the app has its own primary source. |
| pip | `PIP_INDEX_URL`, plus `PIP_TRUSTED_HOST` because the cache speaks plain HTTP |
| uv | `UV_DEFAULT_INDEX`, `UV_PYTHON_INSTALL_MIRROR`. With a `uv.lock` made against pypi.org, `uv sync` re-points the lock at the cache and keeps the locked versions (verified). |
| bun / npm | `NPM_CONFIG_REGISTRY`, which Reflex writes into `.web/bunfig.toml`, and `BUN_CONFIG_REGISTRY` |
| Node.js | `_fetch_node` reads `latest-v22.x/SHASUMS256.txt` (an index), then downloads the tarball from its fixed `v22.23.3/` folder (a file) |
| bun itself | `GITHUB`, the base URL Reflex's bun install script downloads from |
| Playwright | `PLAYWRIGHT_DOWNLOAD_HOST` |

5. If the cache does not answer, the launcher logs `Package cache not reachable` and downloads
   directly, exactly as before the cache existed.

**Dev mode keeps the checkout clean.** A dev install links the app's checkout into the container,
but every file the container changes gets a private copy (`pyproject.toml`, `poetry.lock`, …).
With the cache on, `reflex.lock/` is copied too: bun leaves the registry out of `bun.lock` only
for npm's default registry, so through the cache it writes `http://pkg-cache:3142/npm/…` into
every entry. A lock like that must never reach the repo, since it fails wherever the cache does
not exist. The flip side: frontend lock changes made in a dev container stay in the container,
as `poetry.lock` changes already do.

A container keeps the image it was created from, so only newly created containers use a new
launcher image: rebuild `re-ddns/smart-launcher:latest`, then reinstall an app to use the cache.

## 9. When something fails

| Situation | Result |
|-----------|--------|
| pkg-cache is not running | The launcher downloads directly, after about 5 s of trying the cache |
| pkg-cache stops after an app was installed | The app's next start restores its apt sources and downloads directly |
| Offline, file kept | Served from disk |
| Offline, index kept | The last copy is served (`STALE`), so known versions still install |
| Offline, never downloaded | `502`; the install fails as it would without the cache |
| A download breaks or a check fails | Nothing is kept, the clients' connections are cut, they retry |
| pkg-cache restarts during a download | `tmp/` is emptied at start; clients retry |
| Disk full | Downloads fail as above; free space in `pkg_cache/data/` |
| A kept file is bad anyway | The clients' own hash checks reject it; delete that file and it is downloaded again |

## 10. Security

- **Not an open proxy.** Every route has a fixed upstream, `/apt/` reaches only the allow-listed
  hosts (`PKG_CACHE_APT_HOSTS`), and only GET and HEAD without query strings are served.
- **Not on the LAN.** It is reachable from the Docker network and from `127.0.0.1:3142` on the
  Mac only.
- **Paths are checked.** URL paths are decoded and split into segments; `..`, empty segments,
  NUL, `\`, `#` and segments over 240 bytes are refused before any file path is built.
- **Public packages only.** No credentials are stored or forwarded.

## 11. Design choices

| Chosen | Instead of | Because |
|--------|------------|---------|
| One small server (about 45 MB of memory) | devpi + Verdaccio + apt-cacher-ng + nginx | One container instead of four on a Docker VM that has run out of memory before; one folder, one status page |
| A server | Sharing each tool's cache folder between containers | Poetry's cache is not safe for several processes at once, and every app starts at once after a Docker restart; apt and bun caches have per-tool formats; Node.js and Playwright have no cache to share |
| Telling each tool the cache's URL | A transparent HTTPS proxy | No certificate authority to install in every container; the apps' own traffic is untouched |
| Re-checking indexes after 5 minutes | Keeping them for hours | Installs pick the same versions as without the cache; `PKG_CACHE_META_TTL` trades this for speed |

## 12. Settings and their trade-offs

| Variable (pkg-cache container) | Default | Effect |
|--------------------------------|---------|--------|
| `PKG_CACHE_META_TTL` | `300` | Seconds an index is used without asking upstream. Higher means faster installs, but versions published in that window are not seen |
| `PKG_CACHE_APT_HOSTS` | Debian, NodeSource and Ubuntu hosts | Hosts `/apt/` may fetch from |
| `PKG_CACHE_PYPI_URL`, `PKG_CACHE_NPM_URL`, … | the official sites | Upstreams, e.g. a regional mirror |

What the 300 s default costs, measured: in the second ReflexGrid install, `poetry lock` took
45 s. Every file came from disk; the time went to 54 sequential "has this index changed?"
requests to pypi.org, each about 1.5 s over a phone hotspot.

## 13. Measured

2026-10-15, Docker Desktop on a Mac, internet through an iPhone hotspot (0.3–1 MB/s):

| Test | Result |
|------|--------|
| ReflexGrid install, fresh container, empty cache | 333 s; 168 MB downloaded (73 MB PyPI, 38 MB npm in 288 tarballs, 57 MB Node.js) |
| The same install in a new fresh container | 83 s; no packages downloaded; 165 MB served from disk |
| `apt-get update` plus `jq`, fresh container | 30 s, then 2 s |
| 3 requests at once for one uncached wheel | 1 download, 3 identical correct files |
| Cache without any network (`--network none`) | Indexes `STALE`, files `HIT`; `pip download six` succeeded |
| uv with a `uv.lock` made against pypi.org | Lock re-pointed at the cache; six stayed at the locked 1.16.0 |
| Memory of the cache server | about 43 MB |

## 14. Limits and next steps

- **Not cached:** `git clone` of the app and of reflex_ddns_auth (small, `--depth 1`); the
  `docker build` steps of the images; files apps download while running from fixed URLs
  (the LiveKit apps' `livekit-server`, Whisper models, Ollama models).
- **No automatic eviction:** watch the size on the status page and delete folders under
  `data/files/` when needed.
- **Possible next steps:** pass the cache to image builds through build arguments; let the
  LiveKit apps take their download base URL from an environment variable, so `/github/` can
  serve `livekit-server`; a mirror for `git clone`.

## 15. Code map

| Where | What it does |
|-------|--------------|
| `server.py` `RESOLVERS`, `resolve_*()` | URL → upstream URL, file or index, storage key, TTL, rewrite rules, expected hash |
| `split_tail()`, `_case_safe()` | Path checks; npm case escaping |
| `serve_file()`, `download()`, `Fetch` | File HIT and MISS, one shared download, streaming to joined clients, checks, atomic move |
| `serve_meta()`, `refresh_meta()` | Index HIT, re-check, replace and STALE; URL rewriting |
| `passthrough()` | HEAD requests for files not kept yet |
| `status_page()`, `status_json()`, `housekeeping()` | Status page, `/_status`, counters saved and logged every minute |
| `smart_launcher/entrypoint.sh` section 0.5, `_pkg_cache_poetry_source`, `_fetch_node` | Client side: finding the cache, tool settings, Poetry source, Node.js download |
| `docker-compose.test.yml` service `pkg-cache`, `docker_restart.sh` step 2.6 | Running the service |
