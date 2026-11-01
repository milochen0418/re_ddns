#!/usr/bin/env bash
# macos_music_engine.sh
# ─────────────────────
# Install the music engine on this Mac: ACE-Step (https://github.com/ace-step/ACE-Step-1.5,
# MIT), which makes songs with singing from a description and lyrics, and remakes recordings,
# for Music Studio and the other apps through the AI Hub.
#
# It needs the Mac's own graphics chip, so it can't run inside Docker with the apps. This
# script puts it under ~/.local/share/music_engine and installs a small helper
# (music_engine/music_engine.py) as a LaunchAgent, which the AI Hub talks to: it starts the
# engine when a song is asked for and stops it after a while idle, so the memory goes back.
#
# Which size is installed depends on this Mac: the normal planner from 24 GB of memory
# (10 GB on disk), the small one below (8 GB). The Python environment is about 5 GB more.
#
# Usage:
#   ./macos_music_engine.sh --install            # helper + engine + weights (asks before downloading)
#   ./macos_music_engine.sh --install --yes      # without asking
#   ./macos_music_engine.sh --install --tier small|standard
#   ./macos_music_engine.sh --helper-only        # only the helper; the AI Hub's page offers the rest
#   ./macos_music_engine.sh --status
#   ./macos_music_engine.sh --uninstall          # the helper; --purge removes the engine and weights too

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.reflex-ddns.music-engine"
APP_DIR="$HOME/.re_ddns"
SRC_DIR="$SCRIPT_DIR/music_engine"
DST_DIR="$APP_DIR/music_engine"
CONFIG="$APP_DIR/music-engine.json"
LOG="$APP_DIR/music-engine.log"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
ENGINE_DIR="$HOME/.local/share/music_engine"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") COMMAND [--tier small|standard] [--yes] [--secret <platform secret>]

Installs the music engine (ACE-Step) on this Mac for the AI Hub and Music Studio.

Commands:
  --install       Install the helper, the engine's code and environment, and the weights of
                  the size that fits this Mac. Safe to run again: what is here is kept.
  --helper-only   Install just the helper (standard-library Python, a LaunchAgent). The AI
                  Hub's page then shows what this Mac can hold and installs the rest on a click.
  --status        What is installed, what the helper says.
  --uninstall     Stop and remove the helper. With --purge, the engine and its weights too.
  --help

Options:
  --tier          The size to install (default: what fits this Mac's memory).
  --yes           Don't ask before downloading.
  --secret        The platform's DDNS_AUTH_SECRET, when docker can't read it from re-ddns.

Files:
  $DST_DIR/      the helper
  $CONFIG        port, size, the platform secret (0600)
  $LOG
  $ENGINE_DIR/    the engine, its environment and weights
EOF
}

pick_python() {
    local p
    if xcode-select -p >/dev/null 2>&1 && /usr/bin/python3 -c 'import sys' >/dev/null 2>&1; then
        echo /usr/bin/python3
        return 0
    fi
    for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
        if [[ -n "$p" && -x "$p" ]] && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

# A short-lived token for the helper, signed like the apps' asks to the hub.
helper_call() {
    local py="$1" method="$2" path="$3" body="${4:-}"
    "$py" - "$CONFIG" "$method" "$path" "$body" <<'EOF'
import base64, hashlib, hmac, json, sys, time, urllib.error, urllib.request
cfg = json.load(open(sys.argv[1]))
method, path, body = sys.argv[2], sys.argv[3], sys.argv[4]
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
claims = b64(json.dumps({"aud": "music-engine", "sub": "installer", "exp": int(time.time()) + 60}).encode())
sig = b64(hmac.new(cfg["secret"].encode(), f"{head}.{claims}".encode(), hashlib.sha256).digest())
req = urllib.request.Request(f"http://127.0.0.1:{cfg['port']}{path}", data=body.encode() if body else None, method=method,
                             headers={"Authorization": f"Bearer {head}.{claims}.{sig}", "Content-Type": "application/json"})
try:
    print(urllib.request.urlopen(req, timeout=10).read().decode())
except urllib.error.HTTPError as e:
    sys.exit(f"helper answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
except urllib.error.URLError as e:
    sys.exit(f"helper not answering on 127.0.0.1:{cfg['port']}: {e.reason}")
EOF
}

show_status() {
    local py="$1"
    helper_call "$py" GET /status | "$py" -c '
import json, sys
s = json.load(sys.stdin)
print(f"  Engine        : {s[\"engine\"]} ({s[\"commit\"]}), size {s[\"tier\"]}: {s[\"tiers\"][s[\"tier\"]][\"words\"]}, {s[\"tiers\"][s[\"tier\"]][\"gb\"]} GB")
print(f"  Installed     : {\"yes\" if s[\"installed\"] else (\"code only, weights missing: \" + \", \".join(s[\"missing\"]) if s[\"code\"] else \"no\")}")
print(f"  This Mac      : {s[\"memory_gb\"]} GB memory, {s[\"disk_free_gb\"]} GB free on the disk" + ("" if s["fits"] else f"  (!) {s[\"why_not\"]}"))
print(f"  Engine server : {s[\"server\"]}" + (f" ({s[\"server_error\"]})" if s.get("server_error") else "") + f", stops after {s[\"idle_minutes\"]} min idle")
inst = s.get("install") or {}
if inst.get("state") not in (None, "idle"):
    print(f"  Install job   : {inst[\"state\"]} {inst.get(\"step\", \"\")} " + (f"{inst.get(\"gb_done\")}/{inst.get(\"gb_total\")} GB" if inst.get("gb_total") else "") + (f" ({inst[\"error\"]})" if inst.get("error") else ""))
'
}

wait_until_gone() {
    local i
    for i in $(seq 1 25); do
        launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || return 0
        sleep 0.2
    done
}

platform_secret() {
    if [[ -n "${SECRET:-}" ]]; then
        echo "$SECRET"
        return 0
    fi
    if [[ -f "$CONFIG" ]]; then
        local kept
        kept=$("$1" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("secret",""))' "$CONFIG" 2>/dev/null || true)
        if [[ -n "$kept" ]]; then
            echo "$kept"
            return 0
        fi
    fi
    if command -v docker >/dev/null 2>&1; then
        local got
        got=$(docker exec re-ddns printenv DDNS_AUTH_SECRET 2>/dev/null || true)
        if [[ -n "$got" ]]; then
            echo "$got"
            return 0
        fi
    fi
    return 1
}

install_helper() {
    [[ "$(uname -s)" == "Darwin" ]] || die "The music engine runs on Apple Silicon Macs."
    [[ "$(uname -m)" == "arm64" ]] || die "The music engine needs Apple Silicon (this Mac is $(uname -m))."
    [[ -f "$SRC_DIR/music_engine.py" ]] || die "Missing $SRC_DIR/music_engine.py"
    local py
    py=$(pick_python) || die "No python3 found. Install the Command Line Tools: xcode-select --install"
    local secret
    secret=$(platform_secret "$py") || die "Can't read the platform's secret: is re-ddns running here? Else pass --secret <DDNS_AUTH_SECRET>."
    mkdir -p "$APP_DIR" "$DST_DIR" "$(dirname "$PLIST")" "$ENGINE_DIR"
    chmod 700 "$APP_DIR"
    cp "$SRC_DIR/music_engine.py" "$SRC_DIR/download_weights.py" "$DST_DIR/"
    "$py" - "$CONFIG" "$secret" "${TIER:-}" <<'EOF'
import json, os, sys
path, secret, tier = sys.argv[1:4]
try:
    cfg = json.load(open(path))
except (OSError, ValueError):
    cfg = {}
cfg.setdefault("port", 3144)
cfg["secret"] = secret
if tier:
    cfg["tier"] = tier
fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(json.dumps(cfg, indent=2) + "\n")
os.replace(path + ".tmp", path)
EOF
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
        <string>$DST_DIR/music_engine.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
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
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    wait_until_gone
    launchctl bootstrap "$DOMAIN" "$PLIST" || die "launchctl bootstrap failed"
    local i
    for i in $(seq 1 30); do
        if helper_call "$py" GET /status >/dev/null 2>&1; then
            ok "Helper running ($py), on 127.0.0.1:$("$py" -c 'import json,sys; print(json.load(open(sys.argv[1]))["port"])' "$CONFIG") (containers: host.docker.internal)"
            return 0
        fi
        sleep 0.5
    done
    warn "The helper did not answer within 15 s. Last lines of $LOG:"
    tail -n 8 "$LOG" 2>/dev/null || true
    exit 1
}

install_engine() {
    local py="$1"
    local probe
    probe=$(helper_call "$py" GET /status)
    local tier gb fits why missing code
    read -r tier gb fits why missing code < <("$py" -c '
import json, sys
s = json.loads(sys.argv[1]); t = s["tier"]
print(t, s["tiers"][t]["gb"], "yes" if s["fits"] else "no", json.dumps(s["why_not"]), ",".join(s["missing"]) or "-", "yes" if s["code"] else "no")' "$probe")
    if [[ "$code" == "yes" && "$missing" == "-" ]]; then
        ok "The engine is already installed ($tier)."
        return 0
    fi
    [[ "$fits" == "yes" ]] || die "This Mac can't hold the $tier size: $why. Try --tier small, or free some disk."
    echo
    echo "  Size for this Mac : $tier ($gb GB of weights, about 5 GB of Python environment)"
    echo "  Where             : $ENGINE_DIR"
    echo "  From              : github.com/ace-step/ACE-Step-1.5 and huggingface.co/ACE-Step (MIT)"
    echo
    if [[ "${YES:-}" != "1" ]]; then
        read -rp "Download and install now? (y/N): " answer
        [[ "$answer" =~ ^[Yy]$ ]] || { warn "Not installed. The AI Hub's page can install it later."; return 0; }
    fi
    helper_call "$py" POST /install "{\"tier\": \"$tier\"}" >/dev/null
    local last=""
    while true; do
        sleep 5
        local line
        line=$(helper_call "$py" GET /status | "$py" -c '
import json, sys
s = json.load(sys.stdin); i = s["install"]
done = f" {i.get(\"gb_done\")}/{i.get(\"gb_total\")} GB" if i.get("gb_total") else ""
print(i["state"], i.get("step", ""), done, i.get("error", ""))')
        [[ "$line" != "$last" ]] && echo "  $line" && last="$line"
        case "$line" in
            done*) ok "Installed. The AI Hub's page shows the engine as ready; Music Studio can sing now."; return 0 ;;
            failed*) die "Install failed. See $ENGINE_DIR/install.log" ;;
        esac
    done
}

do_uninstall() {
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    wait_until_gone
    rm -f "$PLIST"
    rm -rf "$DST_DIR"
    ok "Helper removed."
    if [[ "${PURGE:-}" == "1" ]]; then
        rm -rf "$ENGINE_DIR"
        rm -f "$CONFIG"
        ok "Engine and weights removed ($ENGINE_DIR)."
    else
        echo "  The engine and its weights stay in $ENGINE_DIR (--purge removes them)."
    fi
}

COMMAND=""
TIER=""
YES=""
SECRET=""
PURGE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install|--helper-only|--status|--uninstall|--help|-h) COMMAND="$1" ;;
        --tier) TIER="${2:-}"; shift ;;
        --yes) YES=1 ;;
        --secret) SECRET="${2:-}"; shift ;;
        --purge) PURGE=1 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
    shift
done
if [[ -n "$TIER" && "$TIER" != "small" && "$TIER" != "standard" ]]; then
    die "--tier takes small or standard"
fi

case "$COMMAND" in
    --install)
        install_helper
        install_engine "$(pick_python)"
        ;;
    --helper-only)
        install_helper
        echo "  Open the AI Hub's page: its Music engine card shows the size that fits and installs it."
        ;;
    --status)
        if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
            warn "The helper isn't installed. Run: $(basename "$0") --install"
            exit 1
        fi
        py=$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$PLIST" 2>/dev/null || pick_python) || die "No python3 found."
        ok "LaunchAgent $LABEL"
        show_status "$py" || { warn "The helper does not answer. Last lines of $LOG:"; tail -n 8 "$LOG" 2>/dev/null || true; exit 1; }
        ;;
    --uninstall) do_uninstall ;;
    --help|-h|"") usage ;;
esac
