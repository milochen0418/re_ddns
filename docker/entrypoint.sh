#!/usr/bin/env bash
set -euo pipefail

# ── entrypoint.sh ──
# Starts BIND9 (named) and the Reflex dev server inside the container.

log() { echo "[entrypoint] $(date '+%H:%M:%S') $*"; }

log "Hello, ^^ entrypoint.sh — last modified: $(stat -c '%y' "$0" 2>/dev/null || stat -f '%Sm' "$0")"

# ──────────────────────────────────────────────
# 0. Inject TSIG key into BIND9 config files
# ──────────────────────────────────────────────
#
# Priority:
#   a) TSIG_SECRET env var  → use as-is (deterministic across restarts)
#   b) /run/secrets/tsig_secret (Docker Swarm secret)
#   c) not set              → auto-generate a random key once per container
#
# The placeholder __TSIG_SECRET__ in the config templates is replaced in-place
# BEFORE named ever reads them.

BIND_TEMPLATE="/etc/bind/named.conf.local.template"
BIND_LOCAL="/etc/bind/named.conf.local"
RNDC_CONF="/etc/bind/rndc.conf"
SECRET_EXPORT="/etc/bind/tsig-secret.env"   # readable by the Reflex app

# Always start from a clean copy of the template
cp "$BIND_TEMPLATE" "$BIND_LOCAL"

if [[ -n "${TSIG_SECRET:-}" ]]; then
    log "Using TSIG_SECRET from environment variable"
    _secret="$TSIG_SECRET"
elif [[ -f /run/secrets/tsig_secret ]]; then
    log "Using TSIG_SECRET from Docker secret file"
    _secret=$(cat /run/secrets/tsig_secret)
else
    log "No TSIG_SECRET supplied – generating a random key …"
    _secret=$(python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())")
    log "Generated TSIG secret: $_secret"
fi

# Substitute placeholder in both config files
sed -i "s|__TSIG_SECRET__|${_secret}|g" "$BIND_LOCAL" "$RNDC_CONF"

# Persist so Reflex app can discover the key without the user copy-pasting it
mkdir -p "$(dirname "$SECRET_EXPORT")"
printf 'TSIG_KEY_NAME=ddns-key\nTSIG_SECRET=%s\n' "$_secret" > "$SECRET_EXPORT"
chown root:bind "$SECRET_EXPORT"
chmod 640 "$SECRET_EXPORT"

log "TSIG key injected into BIND9 config (secret written to $SECRET_EXPORT)"
unset _secret

# ──────────────────────────────────────────────
# 0.4 Auto-detect system forwarders & expand named.conf template
# ──────────────────────────────────────────────
# Read the container's /etc/resolv.conf to discover whatever DNS the
# system is already configured to use (Docker embedded DNS 127.0.0.11
# on compose networks, or the host's real nameservers on host/bridge
# networking).  This avoids hard-coding specific upstream resolvers.

NAMED_TEMPLATE="/etc/bind/named.conf.template"
NAMED_CONF="/etc/bind/named.conf"

# Always start from a fresh copy of the template
cp "$NAMED_TEMPLATE" "$NAMED_CONF"

_forwarders=""
while IFS= read -r _line; do
    if [[ "$_line" =~ ^nameserver[[:space:]]+([^[:space:]]+) ]]; then
        _forwarders="${_forwarders}${BASH_REMATCH[1]}; "
    fi
done < /etc/resolv.conf

if [[ -z "$_forwarders" ]]; then
    _forwarders="8.8.8.8; 1.1.1.1; "
    log "WARNING: No nameservers found in /etc/resolv.conf – falling back to 8.8.8.8 / 1.1.1.1"
else
    log "Using system forwarders from /etc/resolv.conf: ${_forwarders}"
fi

sed -i "s|__FORWARDERS__|${_forwarders}|g" "$NAMED_CONF"
unset _forwarders _line

# ──────────────────────────────────────────────
# 0.5 Expand zone file templates
# ──────────────────────────────────────────────
# Any file in /etc/bind/zones/*.template is copied to its non-.template
# counterpart at startup. This keeps zone files out of git while the
# templates (safe to commit) remain the source of truth.
ZONES_DIR="/etc/bind/zones"
for tmpl in "$ZONES_DIR"/*.template; do
    [[ -f "$tmpl" ]] || continue
    dest="${tmpl%.template}"
    cp "$tmpl" "$dest"
    log "Zone template expanded: $(basename "$dest")"
done
chown -R bind:bind "$ZONES_DIR"

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

# Patch Vite's allowedHosts so the app is reachable via custom hostnames
# (e.g. home.reflex-ddns.com resolved by the local BIND9).
# Reflex regenerates vite.config.js on each run, so we patch it once here
# just before starting. Vite 7+ requires boolean true (not string "all")
# to fully disable host checking.
VITE_CFG="/app/.web/vite.config.js"
if [[ -f "$VITE_CFG" ]]; then
    if grep -q 'allowedHosts: "all"' "$VITE_CFG"; then
        sed -i 's|allowedHosts: "all"|allowedHosts: true|' "$VITE_CFG"
        log "Patched vite.config.js: allowedHosts = true (was \"all\")"
    elif ! grep -q "allowedHosts" "$VITE_CFG"; then
        sed -i 's|port: process.env.PORT,|port: process.env.PORT,\n    allowedHosts: true,|' "$VITE_CFG"
        log "Patched vite.config.js: allowedHosts = true"
    fi
fi

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
