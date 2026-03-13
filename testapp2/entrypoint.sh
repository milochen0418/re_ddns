#!/usr/bin/env bash
set -euo pipefail

# ── testapp2 entrypoint ──
# 1. Register the test domain via the re-ddns API.
# 2. Patch Vite config if needed.
# 3. Start all services via supervisord:
#      - Xvfb (virtual display)
#      - Fluxbox (window manager)
#      - x11vnc (VNC server)
#      - noVNC / websockify (web VNC on port 6080)
#      - Reflex app (3000/8000)
# 4. Launch Chromium inside the virtual display.

log() { echo "[testapp2] $(date '+%H:%M:%S') $*"; }

log "Starting testapp2 container …"
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
# 3. Create dbus directory for Chromium
# ──────────────────────────────────────────────
mkdir -p /run/dbus || true

# ──────────────────────────────────────────────
# 4. Start all services via supervisord
# ──────────────────────────────────────────────
log "Starting supervisord (Xvfb + Fluxbox + VNC + noVNC + Reflex) …"
log ""
log "╔══════════════════════════════════════════════════════════════╗"
log "║  noVNC (browser view): http://localhost:6080/vnc.html       ║"
log "║  Open this URL on your Mac to see the container's desktop.  ║"
log "╚══════════════════════════════════════════════════════════════╝"
log ""

# Start supervisord in background
/usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf &
SUPERVISOR_PID=$!

# Wait for display to be ready
log "Waiting for virtual display …"
for i in $(seq 1 30); do
    if xdotool getactivewindow > /dev/null 2>&1 || [[ -e /tmp/.X11-unix/X99 ]]; then
        break
    fi
    sleep 1
done
sleep 3
log "Virtual display is ready."

# ──────────────────────────────────────────────
# 5. Launch Chromium + Terminal in the virtual display
# ──────────────────────────────────────────────
CHROMIUM_URL="${CHROMIUM_START_URL:-about:blank}"
log "Launching Chromium → ${CHROMIUM_URL}"

DISPLAY=:99 chromium \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --window-size="${SCREEN_WIDTH},${SCREEN_HEIGHT}" \
    --start-maximized \
    "${CHROMIUM_URL}" &

# Launch a terminal so the user can run CA-install scripts etc.
sleep 2
DISPLAY=:99 xterm -fa "Monospace" -fs 12 -geometry 100x24+0+500 -title "Terminal" &
log "Terminal (xterm) launched."

log "All services started. Container is ready."

# Keep container alive — wait for supervisord
wait $SUPERVISOR_PID
