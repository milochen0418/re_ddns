# pkg-cache — download cache for app installs

How it works inside: [DESIGN.md](DESIGN.md) · 中文設計說明：[DESIGN_ZH.md](DESIGN_ZH.md)

Every App Store install starts a fresh smart-launcher container, and every
container downloads its dependencies from the internet again: apt packages
(`ffmpeg`, fonts), the apt package indexes themselves, PyPI wheels for Poetry
and pip, npm packages for bun, a Node.js build, Playwright's Chromium. Most of
these files are the same for every app and every reinstall.

`pkg-cache` is a small pull-through cache (one Python file, [server.py](server.py))
that sits between the app containers and those download sites. The first
download of a file goes to the internet and is saved in `pkg_cache/data/` on the
host. Every later request for the same file is served from that folder.

## When a cached file is used

- **Files that name one exact version** (`six-1.17.0-py3-none-any.whl`,
  `react-19.0.0.tgz`, `jq_1.6-2.1+deb12u2_arm64.deb`,
  `node-v22.23.3-linux-arm64.tar.gz`, …) never change, so they are kept forever
  and served from disk. A file is reused only for the very same URL: asking for
  another version is always a new download.
- **Package indexes** (PyPI's list of a package's releases, npm package
  documents, apt `InRelease`, Node.js `latest-v22.x/`) change when something is
  published. They are cached, but re-checked upstream after
  `PKG_CACHE_META_TTL` seconds (default 300; apt indexes on every request). The
  check is a conditional request, usually a small `304 Not Modified`. Poetry,
  pip, uv and bun therefore pick the same versions as they would without the
  cache.
- **Offline or upstream down:** indexes are served from their last copy, so
  versions that were installed before can be installed again without internet.
  Anything never downloaded before fails as it would without the cache.

When several containers ask for the same uncached file at once, it is downloaded
once and streamed to all of them while it arrives. Downloaded files are checked
before they are kept: the length always, and the checksum where the URL carries
one (PyPI's BLAKE2b path, apt's `by-hash/SHA256`). The clients still verify
their own hashes as usual.

## Routes

| Route | Upstream | Used by |
|-------|----------|---------|
| `/pypi/simple/<project>/`, `/pypi/files/…` | pypi.org, files.pythonhosted.org | Poetry, pip, uv |
| `/npm/<package>`, `/npm/<package>/-/<file>.tgz` | registry.npmjs.org | bun (through Reflex's `.web/bunfig.toml`), npm |
| `/apt/<host>/…` | `https://<host>/…` for deb.debian.org, security.debian.org, deb.nodesource.com (+ Ubuntu hosts) | apt-get, `playwright install-deps` |
| `/nodejs/dist/…` | nodejs.org | the launcher's Node.js download for Reflex 0.10 apps |
| `/github/<owner>/<repo>/releases/download/<tag>/<file>` | github.com | Reflex's bun installer, uv's Python builds |
| `/playwright/builds/…` | Playwright's CDN | `playwright install chromium` |

## Where the files are

`pkg_cache/data/` on the host (bind-mounted at `/data`). It is in `.gitignore`
and `.dockerignore`, and `docker_restart.sh`'s `down -v` does not touch it.

```
pkg_cache/data/
  files/<route>/<upstream path>   kept files, e.g. files/npm/react/-/react-19.0.0.tgz
  meta/<route>/…                  cached indexes (+ their ETag / fetch time)
  stats.json                      hit / download counters
  tmp/                            downloads in progress
```

The folder can be cleaned at any time, as a whole or per route
(`rm -rf pkg_cache/data/files/npm`); the next install downloads the files again.
Nothing is evicted automatically, so check the size now and then on the status
page.

## Running it

It is the `pkg-cache` service in `docker-compose.test.yml`, and
`./docker_restart.sh` starts it. To start or rebuild only the cache:

```bash
docker compose -f docker-compose.test.yml up -d --build --no-deps pkg-cache
```

## How apps use it

The smart launcher (`smart_launcher/entrypoint.sh`, section 0.5) checks
`http://pkg-cache:3142/_health` on every container start. When the cache
answers, it logs `Package cache: http://pkg-cache:3142 …` and sets:

| Tool | Setting |
|------|---------|
| apt | `deb.debian.org`, `security.debian.org`, `deb.nodesource.com` in the sources → `http://pkg-cache:3142/apt/<host>/` (the originals come back on the next start) |
| Poetry | `[[tool.poetry.source]] name = "pkg-cache"`, priority `primary`, appended to the container's copy of `pyproject.toml` (skipped if the app has its own primary source) |
| pip | `PIP_INDEX_URL`, `PIP_TRUSTED_HOST` |
| uv | `UV_DEFAULT_INDEX`, `UV_PYTHON_INSTALL_MIRROR` |
| bun / npm | `NPM_CONFIG_REGISTRY` (Reflex writes it into `.web/bunfig.toml`), `BUN_CONFIG_REGISTRY` |
| Node.js | the launcher downloads `nodejs/dist/v<version>/…` through the cache |
| bun itself | `GITHUB` (base URL of Reflex's bun install script) |
| Playwright | `PLAYWRIGHT_DOWNLOAD_HOST` |

If the cache is not running, the launcher logs `Package cache not reachable` and
downloads everything directly, as before. To turn it off for one app, give the
container `PKG_CACHE_URL=` (empty).

In dev mode the launcher also copies the app's `reflex.lock/` instead of linking
it: through the cache, bun writes `http://pkg-cache:3142/npm/…` into every entry
of `bun.lock`, and that must not land in your checkout.

The launcher image has to contain this entrypoint: rebuild it with
`docker build -t re-ddns/smart-launcher:latest ./smart_launcher`
(`docker_restart.sh` does this). Only newly created app containers use a new
image, so reinstall an app to pick it up.

## Checking that it works

- Status page: <http://localhost:3142> (files and size per route, hits,
  downloads, MB served from disk vs. fetched upstream). JSON: `/_status`.
- `docker logs -f pkg-cache`: one `MISS` line per file downloaded, plus a
  per-minute summary of hits and downloads.
- An app's log (`docker logs smart-app-<subdomain>`) shows
  `Package cache: …` and `Poetry source: pkg-cache (primary)`.

## Using it from the Mac

The cache listens on `127.0.0.1:3142` too, so local tools can share it:

```bash
pip install --index-url http://localhost:3142/pypi/simple/ --trusted-host localhost:3142 <pkg>
UV_DEFAULT_INDEX=http://localhost:3142/pypi/simple/ uv sync
NPM_CONFIG_REGISTRY=http://localhost:3142/npm/ bun install
```

## Settings (environment of the pkg-cache container)

| Variable | Default | Meaning |
|----------|---------|---------|
| `PKG_CACHE_META_TTL` | `300` | Seconds an index is used before asking upstream again |
| `PKG_CACHE_APT_HOSTS` | Debian, NodeSource, Ubuntu hosts | apt hosts the `/apt/` route may fetch from |
| `PKG_CACHE_PYPI_URL`, `PKG_CACHE_PYPI_FILES_URL`, `PKG_CACHE_NPM_URL`, `PKG_CACHE_NODEJS_URL`, `PKG_CACHE_GITHUB_URL`, `PKG_CACHE_PLAYWRIGHT_URL` | the official sites | Upstream to use instead, e.g. a regional mirror |
| `PKG_CACHE_LOG_LEVEL` | `INFO` | `WARNING` hides the per-file MISS lines and the minute summaries |

## Not cached (yet)

- `git clone` of the app and of reflex_ddns_auth (small, `--depth 1`).
- Image builds (`docker build` of the launcher, re-ddns, App Store): their
  `RUN apt-get` / `npm install -g bun` / Poetry installer steps download
  directly. Docker's own layer cache usually covers them.
- Files apps download at runtime from hard-coded URLs, e.g. the LiveKit apps'
  `livekit-server` release from GitHub, Whisper models from Hugging Face,
  Ollama models. The `/github/` route can serve the first one once the app reads
  its download base URL from an environment variable.
