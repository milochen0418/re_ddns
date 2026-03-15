# TestApp3 – Frontend ↔ Backend Integration Tests

A Docker container running a Reflex app that comprehensively tests all
communication paths between the Reflex frontend and backend when served
behind the re-ddns nginx reverse proxy.

## Purpose

TestApp3 tests what testapp (basic DNS) and testapp2 (browser/HTTPS) do not:
the **correctness of every frontend↔backend communication path** when routed
through nginx with domain-name-based Host headers.

### What it tests

| # | Test | Path | What it proves |
|---|------|------|----------------|
| 1 | State update | `/_event` (WebSocket) | Reflex state sync works through nginx proxy |
| 2 | File upload | `/_upload` (POST) | Multipart upload proxied correctly |
| 3 | File download | `/api/testapp3/download/…` (GET) | Custom API file responses work |
| 4 | Custom API | `/api/testapp3/echo`, `/api/testapp3/server-info` | FastAPI routes reachable via domain |
| 5 | Health | `/ping`, `/_health` | Backend health endpoints respond |

### Why this matters

When a Reflex app is served behind nginx:
- The frontend (compiled JS from Vite on port 3000) makes WebSocket
  connections to `/_event` which nginx must proxy to port 8000.
- File uploads go to `/_upload` on the backend.
- Custom API endpoints under `/api/` go to the backend.
- All of this must work with the **domain name** (e.g.,
  `testapp3.reflex-ddns.com`) rather than `localhost:8000`.

## Architecture

```
Browser
  │
  ▼
nginx (re-ddns :443)
  ├── /_event, /ping, /_upload, /_health, /api  →  test-app3:8000
  └── / (everything else)                       →  test-app3:3000
  │
  ▼
test-app3 container (172.28.0.40)
  ├── Reflex frontend  :3000
  └── Reflex backend   :8000
      ├── /_event       (WebSocket state sync)
      ├── /_upload      (file upload handler)
      ├── /api/testapp3/echo        (custom echo)
      ├── /api/testapp3/files       (list uploads)
      ├── /api/testapp3/download/*  (serve files)
      └── /api/testapp3/server-info (env debug)
```

## Usage

```bash
# Start the full test stack:
docker compose -f docker-compose.test.yml up --build

# Access (after setting DNS to 127.0.0.1 on Mac):
# https://testapp3.reflex-ddns.com
```

## Manual API Testing

```bash
# Echo test:
curl https://testapp3.reflex-ddns.com/api/testapp3/echo?msg=hello

# Server info:
curl https://testapp3.reflex-ddns.com/api/testapp3/server-info

# Upload a file:
curl -F "files=@README.md" https://testapp3.reflex-ddns.com/_upload

# List uploaded files:
curl https://testapp3.reflex-ddns.com/api/testapp3/files
```
