# TestApp2 – Browser-Enabled Test Container

A Docker container that runs a Reflex Hello World app **plus a full Chromium browser** with a virtual display. You can view and control the browser from your Mac via **noVNC** (a web-based VNC client).

## Purpose

TestApp2 extends the basic testapp (testapp1) with the ability to:

1. **Run a real browser inside the container** (Chromium on Xvfb).
2. **View the browser on your Mac** via noVNC at `http://localhost:6080/vnc.html`.
3. **Test CA certificate operations** — download the CA from re-ddns, install it, and verify HTTPS.
4. **Simulate a remote machine** — prove that a browser on a separate host can interact with re-ddns.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  test-app2 container                                    │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐    │
│  │  Xvfb    │→ │ Fluxbox  │  │ Reflex App         │    │
│  │ :99      │  │ (WM)     │  │ (3000 / 8000)      │    │
│  └──────────┘  └──────────┘  └────────────────────┘    │
│       ↓                                                 │
│  ┌──────────┐  ┌──────────────────┐                    │
│  │ x11vnc   │→ │ noVNC/websockify │── port 6080 ──→ Mac│
│  │ :5900    │  │ :6080            │                    │
│  └──────────┘  └──────────────────┘                    │
│       ↓                                                 │
│  ┌────────────────────────────────────┐                 │
│  │ Chromium Browser                   │                 │
│  │ (can access *.reflex-ddns.com)     │                 │
│  └────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# From the repo root
docker compose -f docker-compose.test.yml up --build
```

Then open on your Mac:

| URL | Description |
| --- | --- |
| `http://localhost:6080/vnc.html` | noVNC — see and control the container's Chromium browser |
| `http://home.reflex-ddns.com` | re-ddns UI (set Mac DNS to 127.0.0.1 first) |
| `http://testapp2.reflex-ddns.com` | testapp2 Reflex app |

## Testing CA Download & HTTPS

1. Open `http://localhost:6080/vnc.html` on your Mac.
2. In the container's Chromium, navigate to `http://home.reflex-ddns.com`.
3. Go to the CA Guide page and download the CA certificate.
4. Install the CA in Chromium or the system trust store (follow the on-screen guide).
5. Navigate to `https://home.reflex-ddns.com` — it should work with the green lock.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `RE_DDNS_API_URL` | `http://re-ddns:8000` | re-ddns API endpoint |
| `SERVICE_SUBDOMAIN` | `testapp2` | DNS subdomain to register |
| `SERVICE_ZONE` | `reflex-ddns.com` | DNS zone |
| `SERVICE_IP` | `127.0.0.1` | IP for the A record |
| `SCREEN_WIDTH` | `1280` | Virtual display width |
| `SCREEN_HEIGHT` | `800` | Virtual display height |
| `SCREEN_DEPTH` | `24` | Virtual display color depth |
| `CHROMIUM_START_URL` | `http://home.reflex-ddns.com` | URL Chromium opens on launch |

## Ports

| Port | Service |
| --- | --- |
| 6080 | noVNC (published to host) |
| 3000 | Reflex frontend (internal) |
| 8000 | Reflex backend (internal) |
