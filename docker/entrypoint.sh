#!/usr/bin/env bash
set -euo pipefail

# ── entrypoint.sh ──
# Starts BIND9 (named) and the Reflex dev server inside the container.

log() { echo "[entrypoint] $(date '+%H:%M:%S') $*"; }

# ──────────────────────────────────────────────
# 1. Start BIND9
# ──────────────────────────────────────────────
log "Starting BIND9 (named) …"

# Ensure runtime dirs exist and have correct ownership
mkdir -p /run/named /var/log/bind /var/cache/bind
chown -R bind:bind /run/named /var/log/bind /var/cache/bind /etc/bind/zones

# Validate configuration before starting
if ! named-checkconf /etc/bind/named.conf; then
    log "ERROR: BIND9 configuration check failed!"
    exit 1
fi

# Start named in the foreground but backgrounded so we can also run Reflex
named -u bind -g &
NAMED_PID=$!
log "BIND9 started (PID $NAMED_PID)"

# ──────────────────────────────────────────────
# 2. Wait for BIND9 to be ready
# ──────────────────────────────────────────────
for i in $(seq 1 15); do
    if rndc status >/dev/null 2>&1; then
        log "BIND9 is ready"
        break
    fi
    sleep 1
done

# ──────────────────────────────────────────────
# 3. Start Reflex dev server
# ──────────────────────────────────────────────
log "Starting Reflex app (dev mode) …"
cd /app

# Clean stale PID files / ports from previous runs
rm -f /app/.web/.next/.pid 2>/dev/null || true

# Run Reflex; it watches for file changes automatically in dev mode
poetry run reflex run \
    --env dev \
    --frontend-port 3000 \
    --backend-port 8000 \
    --loglevel info &
REFLEX_PID=$!
log "Reflex started (PID $REFLEX_PID)"

# ──────────────────────────────────────────────
# 4. Signal handling: graceful shutdown
# ──────────────────────────────────────────────
cleanup() {
    log "Shutting down …"
    kill "$REFLEX_PID" 2>/dev/null || true
    rndc stop 2>/dev/null || kill "$NAMED_PID" 2>/dev/null || true
    wait
    log "All processes stopped"
}
trap cleanup SIGTERM SIGINT

# ──────────────────────────────────────────────
# 5. Wait for either process to exit
# ──────────────────────────────────────────────
wait -n "$NAMED_PID" "$REFLEX_PID" 2>/dev/null || true
log "A child process exited – shutting down the other"
cleanup
