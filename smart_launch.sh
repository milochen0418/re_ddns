#!/usr/bin/env bash
set -euo pipefail

# ── smart_launch.sh ──
#
# Launch any GitHub Reflex app behind re-ddns with one command.
#
# Usage:
#   ./smart_launch.sh [OPTIONS] <GITHUB_REPO> <APP_NAME> <SUBDOMAIN> [ENV_FILE]
#
# Options:
#   --branch=<name>   Git branch or tag to checkout (default: main)
#   --commit=<hash>   Git commit SHA to checkout (clones full history)
#   --subdir=<path>   Subdirectory within repo containing the Reflex project
#   --env=<file>      Path to .env file to inject into the app
#   -v <本機路徑>:<容器內路徑>  將本機資料夾掛載進容器 (可重複使用)
#   --volume=<本機路徑>:<容器內路徑>  同 -v
#   --list            List all services launched via smart_launch
#   --remove=<sub>    Remove a launched service (container + DNS + nginx)
#   --help            Show this help and exit
#
# Examples:
#   # Basic:
#   ./smart_launch.sh https://github.com/milochen0418/codoc_in_vecdraw.git codoc_in_vecdraw vecdraw
#   ./smart_launch.sh https://github.com/milochen0418/codoc_in_plantuml.git codoc_in_plantuml plantuml
#   ./smart_launch.sh https://github.com/milochen0418/codoc_in_md.git codoc_in_md md
#   ./smart_launch.sh https://github.com/user/app.git my_app myapp
#
#   # With branch:
#   ./smart_launch.sh --branch=develop https://github.com/user/app.git my_app myapp
#
#   # With specific commit:
#   ./smart_launch.sh --commit=a1b2c3d https://github.com/user/app.git my_app myapp
#
#   # With .env (flag or positional):
#   ./smart_launch.sh --env=./my.env https://github.com/user/app.git my_app myapp
#   ./smart_launch.sh https://github.com/user/app.git my_app myapp ./my.env
#
#   # With volume mount (-v 本機路徑:容器內路徑):
#   # 下面的例子把 Mac 上的 /Users/Shared/DICOM 掛載到容器內的 /Users/Shared/DICOM，
#   # 容器裡下載的 DICOM 檔案會直接寫入你 Mac 本機的該資料夾。
#   ./smart_launch.sh -v /Users/Shared/DICOM:/Users/Shared/DICOM \
#       https://github.com/milochen0418/dicom_data_explorer.git dicom_data_explorer dicom-data-explorer
#
#   # Multiple volumes (可掛載多個資料夾):
#   # -v Mac本機路徑:容器內路徑
#   ./smart_launch.sh -v /data/input:/input -v /data/output:/output \
#       https://github.com/user/app.git my_app myapp
#
#   # Combine options:
#   ./smart_launch.sh --branch=v2.0 --subdir=frontend --env=./prod.env \
#       https://github.com/user/app.git my_app myapp
#
# What it does:
#   1. Validates arguments
#   2. Generates docker-compose.smart-app.yml with your settings
#   3. If an .env file is specified, mounts it into the container
#   4. Ensures re-ddns is running (starts it if not)
#   5. Builds and starts the smart-app container
#   6. Tails logs until the app is ready
#
# To stop a specific app:
#   docker compose -f docker-compose.smart-launcher.yml -f docker-compose.smart-app-<SUBDOMAIN>.yml down smart-app-<SUBDOMAIN>
#
# You can launch multiple apps simultaneously:
#   ./smart_launch.sh https://github.com/user/app1.git app1 app1
#   ./smart_launch.sh https://github.com/user/app2.git app2 app2
#   ./smart_launch.sh https://github.com/milochen0418/codoc_in_vecdraw.git codoc_in_vecdraw vecdraw
#   ./smart_launch.sh https://github.com/milochen0418/codoc_in_plantuml.git codoc_in_plantuml plantuml
#   ./smart_launch.sh https://github.com/milochen0418/codoc_in_md.git codoc_in_md md



SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Auto-detect Mac LAN IP for DNS A records
source "${SCRIPT_DIR}/detect_external_ip.sh"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[smart-launch]${NC} $*"; }
ok()   { echo -e "${GREEN}[smart-launch]${NC} $*"; }
warn() { echo -e "${YELLOW}[smart-launch]${NC} $*"; }
err()  { echo -e "${RED}[smart-launch]${NC} $*" >&2; }

RE_DDNS_API="http://127.0.0.1:8000"
RE_DDNS_CONTAINER="re-ddns"

# Helper: call re-ddns API from inside the container
api_call() {
    # $1 = method (GET, POST, DELETE), $2 = path (e.g. /api/service/list)
    local method="$1" path="$2"
    docker exec "$RE_DDNS_CONTAINER" curl -sf -X "$method" "${RE_DDNS_API}${path}" 2>/dev/null
}

# ──────────────────────────────────────────────
# Helper: --list
# ──────────────────────────────────────────────
do_list() {
    if ! docker ps --format '{{.Names}}' | grep -q '^re-ddns$'; then
        err "re-ddns is not running."
        exit 1
    fi
    local response
    response=$(api_call GET /api/service/list) || {
        err "Failed to reach re-ddns API"
        exit 1
    }

    local count
    count=$(echo "$response" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)

    if [[ "$count" == "0" ]]; then
        log "No services currently registered."
        exit 0
    fi

    echo ""
    log "Registered services ($count):"
    echo ""
    printf "  ${CYAN}%-14s %-30s %-22s %s${NC}\n" "SUBDOMAIN" "URL" "UPSTREAM" "CONTAINER"
    printf "  %-14s %-30s %-22s %s\n" "─────────" "───" "────────" "─────────"

    echo "$response" | python3 -c "
import sys, json
svcs = json.load(sys.stdin)
for s in svcs:
    sub = s['subdomain']
    zone = s['zone']
    host = s['upstream_host']
    fe = s['frontend_port']
    url = f'https://{sub}.{zone}'
    upstream = f'{host}:{fe}'
    container = f'smart-app-{sub}'
    print(f'  {sub:<14} {url:<30} {upstream:<22} {container}')
"
    echo ""
    exit 0
}

# ──────────────────────────────────────────────
# Helper: --remove=<subdomain>
# ──────────────────────────────────────────────
do_remove() {
    local subdomain="$1"
    local container_name="smart-app-${subdomain}"
    local compose_file="$SCRIPT_DIR/docker-compose.smart-app-${subdomain}.yml"

    log "Removing service: ${subdomain}"
    echo ""

    # 1) Stop & remove Docker container
    if docker ps -a --format '{{.Names}}' | grep -q "^${container_name}$"; then
        log "Stopping container ${container_name} ..."
        docker stop "$container_name" 2>/dev/null || true
        docker rm "$container_name" 2>/dev/null || true
        ok "Container ${container_name} removed."
    else
        warn "Container ${container_name} not found (already removed?)."
    fi

    # 2) Call API to delete DNS + nginx + registry entry
    if docker ps --format '{{.Names}}' | grep -q '^re-ddns$'; then
        log "Deleting DNS & nginx records via API ..."
        local response
        response=$(api_call DELETE "/api/service/${subdomain}") || {
            err "Failed to reach re-ddns API"
        }
        local success
        success=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))" 2>/dev/null || echo "False")
        if [[ "$success" == "True" ]]; then
            ok "DNS & nginx records removed."
        else
            warn "Service '${subdomain}' was not in registry (already removed?)."
        fi
    else
        warn "re-ddns is not running — skipping DNS/nginx cleanup."
    fi

    # 3) Clean up generated files
    if [[ -f "$compose_file" ]]; then
        rm -f "$compose_file"
        ok "Removed $compose_file"
    fi
    local env_mount="$SCRIPT_DIR/smart_launcher/.env.mount.${subdomain}"
    if [[ -f "$env_mount" ]]; then
        rm -f "$env_mount"
        ok "Removed $env_mount"
    fi

    echo ""
    ok "Service '${subdomain}' fully removed."
    exit 0
}

# ──────────────────────────────────────────────
# 0. Parse arguments
# ──────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $0 [OPTIONS] <GITHUB_REPO> <APP_NAME> <SUBDOMAIN> [ENV_FILE]

Arguments:
  GITHUB_REPO   GitHub clone URL (e.g. https://github.com/user/repo.git)
  APP_NAME      Reflex app module name (folder containing __init__.py)
  SUBDOMAIN     Subdomain for https://<SUBDOMAIN>.reflex-ddns.com
  ENV_FILE      (Optional) Path to .env file to inject into the app

Options:
  --branch=<name>   Git branch or tag to checkout (default: main)
  --commit=<hash>   Git commit SHA to checkout after cloning
  --subdir=<path>   Subdirectory within repo for the Reflex project
  --env=<file>      Path to .env file (alternative to positional ENV_FILE)
  -v <本機>:<容器>  Mount host dir into container (repeatable)
                    Format: -v /Mac本機路徑:/容器內路徑
  --volume=<本>:<容> Same as -v
  --list            List all services launched via smart_launch
  --remove=<sub>    Remove a launched service (stop container, delete DNS + nginx)
  --help            Show this help and exit

Examples:
  $0 https://github.com/user/app.git my_app myapp
  $0 --branch=develop https://github.com/user/app.git my_app myapp
  $0 --commit=a1b2c3d https://github.com/user/app.git my_app myapp
  $0 --branch=v2.0 --env=./prod.env https://github.com/user/app.git my_app myapp
  $0 https://github.com/milochen0418/codoc_in_vecdraw.git codoc_in_vecdraw vecdraw
  $0 https://github.com/milochen0418/codoc_in_plantuml.git codoc_in_plantuml plantuml
  $0 https://github.com/milochen0418/relack.git relack relack ./relack.env
  $0 --commit=b7d5e26c https://github.com/milochen0418/codoc_in_md.git codoc_in_md md
  $0 https://github.com/milochen0418/codoc_in_md.git codoc_in_md md
  $0 -v /Users/Shared/DICOM:/Users/Shared/DICOM https://github.com/milochen0418/dicom_data_explorer.git dicom_data_explorer dicom-data-explorer
  $0 -v /Users/Shared/DICOM:/Users/Shared/DICOM https://github.com/milochen0418/dicom_viewer.git dicom_viewer dicom-viewer
  $0 https://github.com/milochen0418/video_segment_splitter.git video_segment_splitter video-segment-splitter
  $0 https://github.com/milochen0418/video_duration_adjuster.git video_duration_adjuster video-duration-adjuster

  # List all launched services:
  $0 --list

  # Remove a service:
  $0 --remove=md

EOF
    exit 1
}

# Defaults for optional flags
GITHUB_BRANCH="main"
GITHUB_COMMIT=""
GITHUB_SUBDIR=""
ENV_FILE=""
VOLUMES=()

# Collect positional arguments separately
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch=*)
            GITHUB_BRANCH="${1#*=}"
            shift
            ;;
        --branch)
            GITHUB_BRANCH="${2:-}"
            [[ -z "$GITHUB_BRANCH" ]] && { err "--branch requires a value"; exit 1; }
            shift 2
            ;;
        --commit=*)
            GITHUB_COMMIT="${1#*=}"
            shift
            ;;
        --commit)
            GITHUB_COMMIT="${2:-}"
            [[ -z "$GITHUB_COMMIT" ]] && { err "--commit requires a value"; exit 1; }
            shift 2
            ;;
        --subdir=*)
            GITHUB_SUBDIR="${1#*=}"
            shift
            ;;
        --subdir)
            GITHUB_SUBDIR="${2:-}"
            [[ -z "$GITHUB_SUBDIR" ]] && { err "--subdir requires a value"; exit 1; }
            shift 2
            ;;
        --env=*)
            ENV_FILE="${1#*=}"
            shift
            ;;
        --env)
            ENV_FILE="${2:-}"
            [[ -z "$ENV_FILE" ]] && { err "--env requires a value"; exit 1; }
            shift 2
            ;;
        --volume=*)
            VOLUMES+=("${1#*=}")
            shift
            ;;
        --volume)
            [[ -z "${2:-}" ]] && { err "--volume requires a value (host:container)"; exit 1; }
            VOLUMES+=("$2")
            shift 2
            ;;
        -v)
            [[ -z "${2:-}" ]] && { err "-v requires a value (host:container)"; exit 1; }
            VOLUMES+=("$2")
            shift 2
            ;;
        --list)
            do_list
            ;;
        --remove=*)
            do_remove "${1#*=}"
            ;;
        --remove)
            [[ -z "${2:-}" ]] && { err "--remove requires a subdomain value"; exit 1; }
            do_remove "$2"
            ;;
        --help|-h)
            usage
            ;;
        --*)
            err "Unknown option: $1"
            usage
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

# Restore positional args
if [[ ${#POSITIONAL_ARGS[@]} -lt 3 ]]; then
    err "Missing required arguments (need GITHUB_REPO, APP_NAME, SUBDOMAIN)"
    usage
fi

GITHUB_REPO="${POSITIONAL_ARGS[0]}"
APP_NAME="${POSITIONAL_ARGS[1]}"
SUBDOMAIN="${POSITIONAL_ARGS[2]}"
# Positional ENV_FILE (4th arg) — only if --env was not provided
if [[ -z "$ENV_FILE" ]]; then
    ENV_FILE="${POSITIONAL_ARGS[3]:-}"
fi

# Validate
if [[ ! "$GITHUB_REPO" =~ ^https?:// ]]; then
    err "GITHUB_REPO must be an HTTPS URL: $GITHUB_REPO"
    exit 1
fi

if [[ -n "$ENV_FILE" && ! -f "$ENV_FILE" ]]; then
    err "ENV_FILE not found: $ENV_FILE"
    exit 1
fi

if [[ -n "$GITHUB_COMMIT" ]] && ! [[ "$GITHUB_COMMIT" =~ ^[0-9a-fA-F]{4,40}$ ]]; then
    err "Invalid commit hash: $GITHUB_COMMIT (expected 4-40 hex characters)"
    exit 1
fi

log "Configuration:"
log "  GITHUB_REPO: $GITHUB_REPO"
log "  APP_NAME:    $APP_NAME"
log "  SUBDOMAIN:   $SUBDOMAIN"
log "  BRANCH:      $GITHUB_BRANCH"
[[ -n "$GITHUB_COMMIT" ]] && log "  COMMIT:      $GITHUB_COMMIT"
[[ -n "$GITHUB_SUBDIR" ]] && log "  SUBDIR:      $GITHUB_SUBDIR"
log "  ENV_FILE:    ${ENV_FILE:-(none)}"
if [[ ${#VOLUMES[@]} -gt 0 ]]; then
    log "  VOLUMES:     ${VOLUMES[*]}"
fi
log "  URL:         https://${SUBDOMAIN}.reflex-ddns.com"
echo ""

# ──────────────────────────────────────────────
# 1. Prepare .env file (copy to smart_launcher/)
# ──────────────────────────────────────────────
CONTAINER_NAME="smart-app-${SUBDOMAIN}"
COMPOSE_OVERRIDE="$SCRIPT_DIR/docker-compose.smart-app-${SUBDOMAIN}.yml"

MOUNTED_ENV=""
if [[ -n "$ENV_FILE" ]]; then
    # Copy the .env file to a known location for Docker volume mount
    ENV_DEST="$SCRIPT_DIR/smart_launcher/.env.mount.${SUBDOMAIN}"
    cp "$ENV_FILE" "$ENV_DEST"
    MOUNTED_ENV="$ENV_DEST"
    log "Copied .env to smart_launcher/.env.mount.${SUBDOMAIN}"
fi

# ──────────────────────────────────────────────
# 2. Generate docker-compose.smart-app-${SUBDOMAIN}.yml
# ──────────────────────────────────────────────
# Build the volumes section conditionally
VOLUMES_SECTION=""
_need_volumes=false
if [[ -n "$MOUNTED_ENV" ]] || [[ ${#VOLUMES[@]} -gt 0 ]]; then
    _need_volumes=true
fi
if $_need_volumes; then
    VOLUMES_SECTION="
    volumes:"
    if [[ -n "$MOUNTED_ENV" ]]; then
        VOLUMES_SECTION+="
      - ./smart_launcher/.env.mount.${SUBDOMAIN}:/app/injected.env:ro"
    fi
    for _vol in "${VOLUMES[@]+${VOLUMES[@]}}"; do
        [[ -n "$_vol" ]] && VOLUMES_SECTION+="
      - ${_vol}"
    done
fi

cat > "$COMPOSE_OVERRIDE" <<YAML
# Auto-generated by smart_launch.sh — do not edit manually.
# Re-run smart_launch.sh to regenerate.

services:
  smart-app-${SUBDOMAIN}:
    build:
      context: ./smart_launcher
      dockerfile: Dockerfile
    container_name: ${CONTAINER_NAME}
    hostname: ${CONTAINER_NAME}

    networks:
      ddns-net:

    depends_on:
      - re-ddns

    environment:
      - GITHUB_REPO=${GITHUB_REPO}
      - APP_NAME=${APP_NAME}
      - GITHUB_BRANCH=${GITHUB_BRANCH}
      - GITHUB_COMMIT=${GITHUB_COMMIT}
      - GITHUB_SUBDIR=${GITHUB_SUBDIR}
      - SERVICE_SUBDOMAIN=${SUBDOMAIN}
      - SERVICE_ZONE=reflex-ddns.com
      - RE_DDNS_API_URL=http://re-ddns:8000
      - REFLEX_FRONTEND_HOST=0.0.0.0
      - REFLEX_BACKEND_HOST=0.0.0.0
${VOLUMES_SECTION}
    restart: unless-stopped
YAML

log "Generated $COMPOSE_OVERRIDE"

# ──────────────────────────────────────────────
# 3. Ensure re-ddns is running
# ──────────────────────────────────────────────
COMPOSE_BASE="docker-compose.smart-launcher.yml"
COMPOSE_APP="docker-compose.smart-app-${SUBDOMAIN}.yml"

if docker ps --format '{{.Names}}' | grep -q '^re-ddns$'; then
    ok "re-ddns is already running"
else
    log "Starting re-ddns ..."
    docker compose -f "$COMPOSE_BASE" up -d --build re-ddns
    log "Waiting for re-ddns to be ready ..."
    sleep 10
fi

# ──────────────────────────────────────────────
# 4. Stop old smart-app if running
# ──────────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    warn "Stopping existing ${CONTAINER_NAME} ..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

# ──────────────────────────────────────────────
# 5. Build and start smart-app
# ──────────────────────────────────────────────
log "Building and starting ${CONTAINER_NAME} ..."
docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_APP" up --build -d "smart-app-${SUBDOMAIN}"

echo ""
ok "=========================================="
ok " ${CONTAINER_NAME} is starting!"
ok ""
ok " App:  https://${SUBDOMAIN}.reflex-ddns.com"
ok " Logs: docker logs -f ${CONTAINER_NAME}"
ok "=========================================="
echo ""

# ──────────────────────────────────────────────
# 6. Tail logs until app is ready (or timeout)
# ──────────────────────────────────────────────
log "Tailing logs (Ctrl+C to stop watching — container keeps running) ..."
echo ""

# Follow logs until "App Running" appears or 5 minutes timeout
docker logs -f "$CONTAINER_NAME" 2>&1 | while IFS= read -r line; do
    echo "$line"
    if echo "$line" | grep -q "App Running"; then
        echo ""
        ok "App is ready! Open https://${SUBDOMAIN}.reflex-ddns.com"
        break
    fi
done || true
