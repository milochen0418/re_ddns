#!/usr/bin/env bash
set -euo pipefail

# ── testapp entrypoint ──
# 1. Register the test domain via the re-ddns API.
# 2. Start the Reflex Hello World dev server.

log() { echo "[testapp] $(date '+%H:%M:%S') $*"; }

log "Starting test-app container …"

cd /app

# ──────────────────────────────────────────────
# 1. Register domain in BIND9 via re-ddns API
# ──────────────────────────────────────────────
log "Registering DNS record via re-ddns API …"
poetry run python register_dns.py || log "WARNING: DNS registration failed – continuing anyway"

# ──────────────────────────────────────────────
# 2. Patch Vite allowedHosts (runtime)
# ──────────────────────────────────────────────
VITE_CFG="/app/.web/vite.config.js"
if [[ -f "$VITE_CFG" ]]; then
    if grep -q 'allowedHosts: "all"' "$VITE_CFG"; then
        sed -i 's|allowedHosts: "all"|allowedHosts: true|' "$VITE_CFG"
        log "Patched vite.config.js: allowedHosts = true"
    elif ! grep -q "allowedHosts" "$VITE_CFG"; then
        sed -i 's|port: process.env.PORT,|port: process.env.PORT,\n    allowedHosts: true,|' "$VITE_CFG"
        log "Patched vite.config.js: allowedHosts = true"
    fi
fi

# ──────────────────────────────────────────────
# 3. Start Reflex dev server
# ──────────────────────────────────────────────
log "Starting Reflex dev server on ports 3000/8000 …"
exec poetry run reflex run \
    --env dev \
    --frontend-port 3000 \
    --backend-port 8000 \
    --loglevel info
