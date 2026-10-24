#!/usr/bin/env bash
# macos_docker_vm_helper.sh
# ─────────────────────────
# Install the small Mac-side helper that lets the App Store's Memory page
# (https://aapps.reflex-ddns.com/monitor) change the Docker VM's memory.
#
# The App Store runs inside Docker Desktop's VM and cannot reach Docker
# Desktop's settings.  The helper (docker_vm_helper/docker_vm_helper.py) runs
# on the Mac as a LaunchAgent, listens on 127.0.0.1 only, and changes that one
# setting when the page asks with the right token.  See the docstring there.
#
# Usage:
#   ./macos_docker_vm_helper.sh --install     # install + start (and at every login)
#   ./macos_docker_vm_helper.sh --status      # is it running, what Docker Desktop has now
#   ./macos_docker_vm_helper.sh --uninstall   # stop and remove

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.reflex-ddns.docker-vm-helper"
APP_DIR="$HOME/.re_ddns"
SCRIPT_SRC="$SCRIPT_DIR/docker_vm_helper/docker_vm_helper.py"
SCRIPT_DST="$APP_DIR/docker_vm_helper.py"
CONFIG="$APP_DIR/docker-vm-helper.json"
LOG="$APP_DIR/docker-vm-helper.log"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
BACKEND_SOCK="$HOME/Library/Containers/com.docker.docker/Data/backend.sock"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") COMMAND

Lets the App Store's Memory page change Docker Desktop's VM memory.

Commands:
  --install     Copy the helper to $APP_DIR and start it as a LaunchAgent
                (it also starts at every login). Safe to run again, e.g.
                after pulling a new version.
  --status      Show whether the helper runs and what Docker Desktop's
                memory setting is now.
  --uninstall   Stop the helper and remove its files. Docker Desktop keeps
                the memory size it has.
  --help        Show this help message and exit.

Files:
  $SCRIPT_DST    the helper
  $CONFIG   port + token (the App Store reads it)
  $LOG    its log
  $PLIST
EOF
}

# The helper needs only the standard library.  /usr/bin/python3 belongs to the
# Command Line Tools; without them it just opens an installer dialog, so check
# for them first and fall back to another python3.
pick_python() {
    local p
    if xcode-select -p >/dev/null 2>&1 && /usr/bin/python3 -c 'import sys' >/dev/null 2>&1; then
        echo /usr/bin/python3
        return 0
    fi
    for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
        if [[ -n "$p" && -x "$p" ]] && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

# GET /vm from the helper, printed as a few readable lines.
show_vm() {
    local py="$1"
    "$py" - "$CONFIG" <<'EOF'
import json, sys, urllib.error, urllib.request
cfg = json.load(open(sys.argv[1]))
req = urllib.request.Request(
    f"http://127.0.0.1:{cfg['port']}/vm",
    headers={"X-Docker-VM-Helper-Token": cfg["token"]},
)
try:
    vm = json.load(urllib.request.urlopen(req, timeout=5))
except urllib.error.HTTPError as e:
    sys.exit(f"  helper answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
except urllib.error.URLError as e:
    sys.exit(f"  helper not answering on 127.0.0.1:{cfg['port']}: {e.reason}")
gb = lambda mib: f"{mib / 1024:g} GB"
print(f"  Docker VM memory : {gb(vm['memory_mib'])}  (Docker Desktop allows {gb(vm['min_mib'])}–{gb(vm['max_mib'])})")
print(f"  This Mac         : {gb(vm['host_mib'])}")
job = vm.get("job") or {}
if job:
    print(f"  Last change      : {gb(job['from_mib'])} → {gb(job['to_mib'])}, {job['state']}"
          + (f" ({job['error']})" if job.get("error") else ""))
print(f"  Listening on     : 127.0.0.1:{cfg['port']}  (containers: host.docker.internal:{cfg['port']})")
EOF
}

wait_until_gone() {
    local i
    for i in $(seq 1 25); do
        launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || return 0
        sleep 0.2
    done
}

do_install() {
    [[ "$(uname -s)" == "Darwin" ]] || die "This helper is for Docker Desktop on macOS."
    [[ -f "$SCRIPT_SRC" ]] || die "Missing $SCRIPT_SRC"
    if [[ ! -S "$BACKEND_SOCK" ]]; then
        warn "Docker Desktop's settings socket is missing ($BACKEND_SOCK)."
        warn "Start Docker Desktop; the helper will reach it once it runs."
    fi
    local py
    py=$(pick_python) || die "No python3 found. Install the Command Line Tools: xcode-select --install"

    mkdir -p "$APP_DIR" "$(dirname "$PLIST")"
    chmod 700 "$APP_DIR"
    cp "$SCRIPT_SRC" "$SCRIPT_DST"

    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$py</string>
        <string>$SCRIPT_DST</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
EOF

    # Replace a running copy (an older version, or a reinstall).
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    wait_until_gone
    launchctl bootstrap "$DOMAIN" "$PLIST" || die "launchctl bootstrap failed"

    local i
    for i in $(seq 1 30); do
        if [[ -f "$CONFIG" ]] && show_vm "$py" >/dev/null 2>&1; then
            ok "Helper running ($py)"
            show_vm "$py"
            echo
            echo "  Change the size on https://aapps.reflex-ddns.com/monitor (Docker VM memory → Resize)."
            return 0
        fi
        sleep 0.5
    done
    warn "The helper did not answer within 15 s. Last lines of $LOG:"
    tail -n 8 "$LOG" 2>/dev/null || true
    exit 1
}

do_status() {
    if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        warn "Not installed. Run: $(basename "$0") --install"
        exit 1
    fi
    local state pid
    state=$(launchctl print "$DOMAIN/$LABEL" | awk -F' = ' '/^\tstate = /{print $2; exit}')
    pid=$(launchctl print "$DOMAIN/$LABEL" | awk -F' = ' '/^\tpid = /{print $2; exit}')
    ok "LaunchAgent $LABEL: ${state:-unknown}${pid:+ (pid $pid)}"
    local py
    py=$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$PLIST" 2>/dev/null || pick_python) \
        || die "No python3 found."
    if [[ -f "$CONFIG" ]] && show_vm "$py"; then
        return 0
    fi
    warn "The helper does not answer. Last lines of $LOG:"
    tail -n 8 "$LOG" 2>/dev/null || true
    exit 1
}

do_uninstall() {
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    wait_until_gone
    rm -f "$PLIST" "$SCRIPT_DST" "$CONFIG" "$CONFIG.tmp" "$LOG"
    rmdir "$APP_DIR" 2>/dev/null || true
    ok "Helper removed. Docker Desktop keeps the memory size it has now."
}

case "${1:-}" in
    --install)   do_install ;;
    --status)    do_status ;;
    --uninstall) do_uninstall ;;
    --help|-h)   usage ;;
    *)           usage; exit 1 ;;
esac
