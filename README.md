# Re-DDNS (Dynamic Domain Name Server by Reflex)

 by Python Reflex
> Important: Before working on this project, read [AGENTS.md](AGENTS.md) for required workflows and tooling expectations.

## Usage Guide


## Documentation

This project includes a **Software Design Document (SDD)** that covers the system architecture, component design, data flow, and technical decisions:

## Getting Started

> Before making changes, read the project guidelines in [AGENTS.md](AGENTS.md).

This project is managed with [Poetry](https://python-poetry.org/).

### Prerequisites

Based on this project's dependencies, install the following system-level packages first via Homebrew (macOS):

```bash
brew install python@3.11  poetry
```

| Package | Reason |
|---------|--------|
| `python@3.11` | The project requires Python ~3.11 as specified in `pyproject.toml` |
| `poetry` | Python dependency manager used to manage this project |

After installing Playwright (via `poetry install`), you also need to download browser binaries:

```bash
poetry run playwright install
```


### Installation

1. (Recommended) Configure Poetry to store the virtual environment inside the project directory. This makes it easier for IDEs and AI agents to discover and analyze dependency source code:

```bash
poetry config virtualenvs.in-project true
```

> This is a global one-time setting. After this, every project will create its `.venv/` under the project root instead of a shared cache folder (`~/Library/Caches/pypoetry/virtualenvs/`). The `.venv/` directory is already in `.gitignore`.

2. Ensure Poetry uses Python 3.11:

```bash
poetry env use python3.11
poetry env info
```

3. Install dependencies:

```bash
poetry install
```

### Running the App

Start the development server:

```bash
poetry run ./reflex_rerun.sh
```

The application will be available at `http://localhost:3000`.

### Clean Rebuild & Run

To fully clean the environment, reinstall all dependencies, and start the app in one step:

```bash
./proj_reinstall.sh --with-rerun
```

This will remove existing Poetry virtual environments and Reflex artifacts, recreate the environment from scratch, and automatically launch the app afterwards.

---

## Docker: Running with BIND9 (DDNS Server)

The project includes a Docker setup that runs **BIND9** (authoritative DNS) together with the **Reflex app** in a single container. This lets your Mac serve as a DDNS server on port 53, controlled via the web UI on port 3000.

### Architecture

```
┌─────────────── Docker Container ───────────────┐
│                                                 │
│   BIND9 (named)          Reflex App             │
│   ├─ port 53 (DNS)       ├─ port 3000 (UI)     │
│   └─ dynamic updates     └─ port 8000 (API)    │
│         via RFC 2136                            │
│                                                 │
│   The Reflex app sends DNS updates to BIND9     │
│   on 127.0.0.1 inside the container.            │
└────────┬────────────┬──────────────┬────────────┘
         │ :53        │ :3000        │ :8000
    ─────┴────────────┴──────────────┴──── Host Mac
```

### Prerequisites

- [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop)

### Quick Start

**1. Generate a TSIG key** (one-time):

```bash
./docker/generate_tsig_key.sh
```

This creates a shared secret used by both BIND9 and the Reflex app to authenticate DNS updates.

**2. (Optional) Customize your domain**:

Edit `docker/named.conf.local` and `docker/zones/db.reflex-ddns.com` — replace `reflex-ddns.com` with your actual domain.

**3. Free port 53 on macOS** (if occupied):

macOS runs a local DNS stub resolver. To free port 53:

```bash
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist
```

To restore it later:

```bash
sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist
```

**4. Build & run**:

```bash
docker compose up --build
```

**5. Open the UI**: visit `http://localhost:3000`

In the configuration form, enter:
| Field | Value |
|-------|-------|
| Server IP | `127.0.0.1` |
| Zone Name | `reflex-ddns.com` (or your domain) |
| Record Name | `home` |
| Key Name | `ddns-key` |
| Key Secret | *(the secret printed by `generate_tsig_key.sh`)* |

**6. Test DNS resolution** from your Mac:

```bash
dig @127.0.0.1 home.reflex-ddns.com A
```

### Live Reload (Development)

The `re_ddns/` source directory is mounted into the container as a volume. When you edit Python files on your Mac, the Reflex dev server inside Docker detects the changes and reloads automatically — no rebuild needed.

Only a full rebuild (`docker compose up --build`) is required when you change:
- `pyproject.toml` / `poetry.lock` (new dependencies)
- `Dockerfile` or files under `docker/` (BIND9 config)

### Useful Commands

```bash
# View logs
docker compose logs -f

# Enter the container
docker exec -it re-ddns bash

# Check BIND9 status
docker exec re-ddns rndc status

# Query a record
docker exec re-ddns dig @127.0.0.1 home.reflex-ddns.com

# Rebuild after dependency changes
docker compose up --build

# Stop everything
docker compose down
```

---

## Test Containers: testapp & testapp2

The project includes two test containers for integration testing and development. They are orchestrated alongside the main re-ddns container via `docker-compose.test.yml`.

### Quick Start

```bash
docker compose -f docker-compose.test.yml up --build
```

After startup:
| URL | Description |
|-----|-------------|
| `http://home.reflex-ddns.com` | Re-DDNS dashboard |
| `http://testapp.reflex-ddns.com` | testapp Hello World |
| `http://testapp2.reflex-ddns.com` | testapp2 Hello World |
| `http://localhost:6080/vnc.html` | noVNC — view testapp2's in-container browser |

### testapp — Lightweight Service Registration Test

A minimal Reflex "Hello World" app that verifies the **DNS + nginx auto-registration** flow:

- On startup, calls `POST /api/service/register` to register itself in BIND9 and nginx.
- Auto-detects its own container IP for DNS registration (no hardcoding needed).
- Proves that a new service can join the re-ddns network with a single API call.

### testapp2 — In-Container Browser Test Environment

Extends testapp with a **full GUI desktop** (Xvfb + Fluxbox + Chromium + noVNC), designed for testing flows that require a real browser:

- **CA certificate install**: Test the Linux CA install script (with zenity GUI) inside the container's terminal.
- **HTTPS verification**: After installing the CA, restart Chromium and verify `https://home.reflex-ddns.com` shows a trusted lock icon.
- **Remote machine simulation**: The container acts as a separate "machine" on the Docker network, proving cross-host DNS resolution and certificate trust.

View the container's desktop from your Mac at `http://localhost:6080/vnc.html`. An **xterm terminal** and **Chromium browser** are auto-launched on startup. Right-click the desktop to open more windows via the Fluxbox menu.

See [testapp/README.md](testapp/README.md) and [testapp2/README.md](testapp2/README.md) for detailed architecture diagrams.
