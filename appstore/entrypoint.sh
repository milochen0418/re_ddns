#!/usr/bin/env bash
set -euo pipefail

# ── appstore entrypoint ──
# 1. Register the aapps subdomain via the re-ddns API.
# 2. Start the Reflex App Store dev server.

log() { echo "[appstore] $(date '+%H:%M:%S') $*"; }

log "Starting app-store container …"

cd /app

# ──────────────────────────────────────────────
# 1. Register domain in BIND9 via re-ddns API
# ──────────────────────────────────────────────
log "Registering DNS record via re-ddns API …"
poetry run python register_dns.py || log "WARNING: DNS registration failed – continuing anyway"

# ──────────────────────────────────────────────
# 2. Start Reflex dev server
# ──────────────────────────────────────────────
# Vite allowedHosts comes from rxconfig.py (vite_allowed_hosts): Reflex 0.10
# rewrites .web/vite.config.js on every run, so patching the file would not stick.
log "Starting Reflex dev server on ports 3000/8000 …"
exec poetry run reflex run \
    --env dev \
    --frontend-port 3000 \
    --backend-port 8000 \
    --loglevel info
