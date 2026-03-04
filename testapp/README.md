# Test App: Verifying Re-DDNS via Docker

This directory contains a **minimal Reflex "Hello World" app** that is used to
test the Re-DDNS system end-to-end.  On startup the container:

1. Calls the **Re-DDNS REST API** (`POST /api/dns/update`) to register DNS
   records in BIND9 — for itself and for the re-ddns UI/API domains.
2. Starts a Reflex dev server on **port 3001**.
3. An **nginx reverse proxy** on port 80 routes traffic by `Host` header:
   - `home.reflex-ddns.com`    → re-ddns (DDNS dashboard)
   - `api.reflex-ddns.com`     → re-ddns (FastAPI backend)
   - `testapp.reflex-ddns.com` → test-app (Hello World)

All domains resolve to `127.0.0.1` — nginx distinguishes them.

## Architecture

```
┌─────────────────────── Docker Network ────────────────────────────┐
│                                                                   │
│  ┌── proxy (nginx) ───────────────────────────────────────────┐   │
│  │  Listens :80                                               │   │
│  │  home.reflex-ddns.com     → re-ddns:3000                  │   │
│  │  api.reflex-ddns.com      → re-ddns:8000                  │   │
│  │  testapp.reflex-ddns.com  → test-app:3000                 │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌── re-ddns ─────────────────────────────────────────────────┐   │
│  │  BIND9        @ :53   (DNS)                                │   │
│  │  Reflex UI    @ :3000 ← standard port                     │   │
│  │  FastAPI API  @ :8000 ← standard port                     │   │
│  └────────────────────────────────────────────────────────────┘   │
│            ▲                                                      │
│            │  HTTP: register DNS records                          │
│  ┌── test-app ────────────────────────────────────────────────┐   │
│  │  Reflex Hello World                                        │   │
│  │  @ :3000 / :8000  ← same ports, no conflict!              │   │
│  │  On startup → registers: testapp, home, api                │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌── future-app (example) ────────────────────────────────────┐   │
│  │  Another Reflex app                                        │   │
│  │  @ :3000 / :8000  ← still no conflict!                    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
└──────┬──────────────┬─────────────────────────────────────────────┘
       │ :53          │ :80   ← only these two ports on the host
  ─────┴──────────────┴────── Host Mac
```

## Quick Start

### 1. Free port 53 on macOS (if needed)

```bash
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist
```

### 2. Build & start all containers

```bash
docker compose -f docker-compose.test.yml up --build
```

### 3. Point Mac DNS at the local BIND9

```bash
# Set DNS for the active interface (e.g. Wi-Fi)
sudo networksetup -setdnsservers Wi-Fi 127.0.0.1
```

Or use the helper script in the repo root:

```bash
sudo ./macos_set_dns.sh 127.0.0.1
```

### 4. Verify

```bash
# Check the API
curl http://api.reflex-ddns.com/api/dns/status

# Query DNS directly
dig @127.0.0.1 testapp.reflex-ddns.com A
dig @127.0.0.1 home.reflex-ddns.com A

# Open apps via domain name (all on port 80 via nginx)
open http://home.reflex-ddns.com        # re-ddns dashboard
open http://testapp.reflex-ddns.com     # test-app Hello World
```

### 5. Restore DNS when done

```bash
sudo networksetup -setdnsservers Wi-Fi empty
sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TEST_DOMAIN_NAME` | `testapp` | Subdomain to register for this test app |
| `ZONE_NAME` | `reflex-ddns.com` | DNS zone |
| `REGISTER_IP` | `127.0.0.1` | IP all DNS records should point to |
| `ALSO_REGISTER` | `home,api` | Extra subdomains to register (comma-separated) |
| `RE_DDNS_API_URL` | `http://re-ddns:8000` | Re-DDNS API base URL |

## Re-DDNS REST API

The main re-ddns app now exposes FastAPI endpoints:

### `GET /api/dns/status`

Health check.  Returns `{"status": "ok", "service": "re-ddns"}`.

### `POST /api/dns/update`

Create or update a DNS record.

**Request body:**

```json
{
  "server_ip": "127.0.0.1",
  "zone_name": "reflex-ddns.com",
  "record_name": "testapp",
  "record_type": "A",
  "ttl": 60,
  "ip_address": "127.0.0.1",
  "key_name": "ddns-key",
  "key_secret": "<base64-tsig-secret>"
}
```

`key_name` and `key_secret` are optional — the server falls back to its own
TSIG credentials when they are omitted.

**Response:**

```json
{
  "success": true,
  "message": "Updated testapp.reflex-ddns.com (A) -> 127.0.0.1 (TTL 60)"
}
```
