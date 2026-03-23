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

## macOS Client Setup Tools

Two scripts help configure macOS machines to use the Re-DDNS service:

### `macos_set_dns.sh` — Local DNS Configuration

Configures the **current Mac** to route `*.reflex-ddns.com` queries to the Docker BIND9 running locally.

```bash
# Show current DNS settings
./macos_set_dns.sh --list

# Join: prepend local BIND9 (127.0.0.1) to DNS, set /etc/resolver and /etc/hosts
./macos_set_dns.sh --join

# Leave: revert to DHCP-provided DNS, remove resolver and hosts entries
./macos_set_dns.sh --leave

# Use a custom DNS IP or network interface
./macos_set_dns.sh --join --dns 192.168.1.10 --iface Ethernet
```

### `remote_install_ca.sh` — Remote Mac Setup (CA + DNS)

Configures a **remote Mac** over SSH — installs the Re-DDNS Root CA certificate and sets up DNS in one step, so the remote Mac can browse `https://*.reflex-ddns.com` without certificate warnings.

```
┌──────────────────┐  SSH/SCP   ┌──────────────────┐
│  This Mac        │ ─────────► │  Remote Mac      │
│  (Docker BIND9)  │            │  (172.20.10.2)   │
│                  │            │                  │
│  • BIND9 :53     │◄─ DNS ────│  • CA installed  │
│  • Reflex :3000  │            │  • DNS → This Mac│
│  • nginx :443    │◄─ HTTPS ──│  • Browser ready │
└──────────────────┘            └──────────────────┘
```

**Prerequisites — set up SSH key login first:**

```bash
# Generate an SSH key (if you don't have one)
ssh-keygen -t ed25519

# Copy your public key to the remote Mac (one-time)
ssh-copy-id milochen@172.20.10.2
```

**Run:**

```bash
# Default target (milochen@172.20.10.2)
./remote_install_ca.sh

# Or specify a different remote Mac
./remote_install_ca.sh john@192.168.1.50
```

The script will:
1. Check SSH connectivity
2. Download the CA certificate locally, copy it via `scp`, and install it as a trusted root in the remote Mac's System Keychain
3. Copy `macos_set_dns.sh` to the remote Mac and run `--join --dns <this-Mac-IP>`, pointing DNS to this Mac's BIND9
4. Verify DNS resolution with `nslookup`

After completion, restart the browser on the remote Mac. Run `./remote_install_ca.sh --help` for full details.

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

<p align="center">
  <img src="docs/images/mac-browser-testapp-https.png" width="720" alt="testapp accessed via HTTPS on Mac browser">
</p>

A minimal Reflex "Hello World" app that verifies the **DNS + nginx auto-registration** flow:

- On startup, calls `POST /api/service/register` to register itself in BIND9 and nginx.
- Auto-detects its own container IP for DNS registration (no hardcoding needed).
- Proves that a new service can join the re-ddns network with a single API call.

### testapp2 — In-Container Browser Test Environment

<p align="center">
  <img src="docs/images/mac-browser-testapp2-https.png" width="720" alt="testapp2 accessed via HTTPS on Mac browser">
</p>

Extends testapp with a **full GUI desktop** (Xvfb + Fluxbox + Chromium + noVNC), designed for testing flows that require a real browser:

- **CA certificate install**: Test the Linux CA install script (with zenity GUI) inside the container's terminal.
- **HTTPS verification**: After installing the CA, restart Chromium and verify `https://home.reflex-ddns.com` shows a trusted lock icon.
- **Remote machine simulation**: The container acts as a separate "machine" on the Docker network, proving cross-host DNS resolution and certificate trust.

View the container's desktop from your Mac at `http://localhost:6080/vnc.html`. An **xterm terminal** and **Chromium browser** are auto-launched on startup. Right-click the desktop to open more windows via the Fluxbox menu.

<p align="center">
  <img src="docs/images/novnc-ca-setup-page.png" width="720" alt="noVNC desktop showing CA Setup page and terminal">
</p>

See [testapp/README.md](testapp/README.md) and [testapp2/README.md](testapp2/README.md) for detailed architecture diagrams.

### How Container-to-Container HTTPS Works

When testapp2's Chromium opens `https://testapp.reflex-ddns.com`, several layers work together to make this possible. Here is the full chain:

```
testapp2 (Chromium)                      re-ddns                           test-app
  │                                        │                                 │
  │ 1. DNS query:                          │                                 │
  │    testapp.reflex-ddns.com → ?         │                                 │
  │ ──────────────────────────────────► BIND9 (port 53)                      │
  │ ◄────────────────────────────────── A 172.28.0.10  ← re-ddns's own IP    │
  │                                        │                                 │
  │ 2. TLS handshake (HTTPS):              │                                 │
  │ ──────────────────────────────────► nginx (port 443)                     │
  │    verify cert → Local CA signed ✅     │                                 │
  │                                        │                                 │
  │ 3. Reverse proxy:                      │                                 │
  │                                    nginx routes to ──────────────────► Reflex
  │                                    test-app:3000/8000                  (port 3000)
  │                                        │                                 │
  │ 4. Response flows back:                │                                 │
  │ ◄────────────────────────────────── ◄──────────────────────────────── HTML/WS
```

This chain involves **five key subsystems**, each solving a different problem:

#### 1. DNS — All domains resolve to re-ddns (the proxy)

When a service (testapp, testapp2) starts, it calls `POST /api/service/register` on re-ddns. The re-ddns server uses **its own container IP** (e.g. `172.28.0.10`) — not the caller's IP — to create the BIND9 A record. This is critical: HTTPS terminates at re-ddns's nginx, so all `*.reflex-ddns.com` DNS records must point there.

```
testapp.reflex-ddns.com   → 172.28.0.10   (re-ddns, where nginx lives)
testapp2.reflex-ddns.com  → 172.28.0.10   (same)
home.reflex-ddns.com      → 172.28.0.10   (same)
```

If DNS pointed to the service containers directly (e.g. `172.28.0.20`), HTTPS would fail because those containers don't run nginx or have TLS certificates.

#### 2. TLS Certificates — Local CA with wildcard support

re-ddns runs a **Local Certificate Authority** (`cert_manager.py`). When a service registers, re-ddns automatically:

1. Generates a private key + CSR for `<subdomain>.reflex-ddns.com`
2. Signs it with the Local CA root certificate
3. Stores it at `/app/data/certs/<domain>/fullchain.pem`

The CA root certificate (`re_ddns_ca.pem`) is the trust anchor — any browser that imports it will trust all `*.reflex-ddns.com` certificates.

#### 3. nginx — Unified HTTPS reverse proxy

re-ddns's nginx (`nginx_manager.py`) generates a config file per service:

- **Port 443 (HTTPS)**: Terminates TLS using the Local CA-signed certificate, then proxies to the upstream service's Reflex ports (3000 for frontend, 8000 for backend/WebSocket).
- **Port 80 (HTTP)**: Redirects to HTTPS.
- **WebSocket support**: Passes `Upgrade` / `Connection` headers for Reflex's real-time `/_event` channel.

The nginx config uses Docker service names (e.g. `test-app:3000`) for upstream routing — Docker's internal DNS resolves these to the correct container IPs.

#### 4. CA Trust — Install script with GUI

For Chromium to show the green lock icon (not "Your connection is not private"), the Local CA certificate must be imported into the browser's trust store. re-ddns provides install scripts at `GET /api/ca/install-script/{platform}`:

| Platform | Trust mechanism |
|----------|----------------|
| **macOS** | `security add-trusted-cert` → System Keychain (AppleScript GUI) |
| **Linux** (testapp2) | `update-ca-certificates` (system) + `certutil` (Chromium NSS DB) with zenity GUI |

Inside testapp2's noVNC desktop, the user runs the Linux install script from the xterm terminal. The script auto-installs `zenity` and `libnss3-tools` if missing, then presents a GUI dialog.

#### 5. Smart protocol detection — ws:// → wss://

Reflex defaults to `ws://` for WebSocket connections. When served over HTTPS, the browser blocks mixed content (`wss://` is required). re-ddns injects a JavaScript snippet that monkey-patches the `WebSocket` constructor to auto-upgrade `ws://` → `wss://` when the page is loaded over HTTPS.

#### Summary: What makes it all work together

| Problem | Solution |
|---------|----------|
| Service containers don't have HTTPS | nginx on re-ddns terminates TLS for all services |
| DNS must route to to the proxy, not the service itself | Server-side registration overrides IP to re-ddns's own IP |
| Browsers don't trust self-signed certs | Local CA + install scripts for each OS |
| Chromium has its own cert store (NSS) | `certutil` installs CA into `~/.pki/nssdb` |
| WebSocket fails over HTTPS with ws:// | JavaScript monkey-patch auto-upgrades to wss:// |
| Need to test from a "remote" browser | testapp2 provides Chromium + noVNC inside Docker |
