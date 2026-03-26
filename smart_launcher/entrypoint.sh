#!/usr/bin/env bash
set -euo pipefail

# ── smart_launcher entrypoint ──
#
# A generic Docker entrypoint that can launch ANY Reflex app from a
# GitHub repo.  Just provide environment variables and let it handle
# everything: clone → install → register DNS → patch Vite → start.
#
# Required environment variables:
#   GITHUB_REPO        – Full GitHub clone URL (HTTPS)
#                        e.g. https://github.com/user/my-reflex-app.git
#   APP_NAME           – Reflex app module name (the folder with __init__.py)
#                        e.g. my_app
#
# Optional environment variables:
#   GITHUB_BRANCH      – Branch/tag to checkout (default: main)
#   GITHUB_COMMIT      – Specific commit SHA to checkout after cloning
#   GITHUB_SUBDIR      – Subdirectory within repo containing the Reflex project
#                        (default: "" = repo root)
#   SERVICE_SUBDOMAIN  – Subdomain for DNS registration (default: APP_NAME)
#   SERVICE_ZONE       – DNS zone (default: reflex-ddns.com)
#   SERVICE_IP         – IP for DNS A record (auto-detected if unset)
#   RE_DDNS_API_URL    – re-ddns API base URL (default: http://re-ddns:8000)
#   FRONTEND_PORT      – Reflex frontend port (default: 3000)
#   BACKEND_PORT       – Reflex backend port (default: 8000)
#   SKIP_DNS_REGISTER  – Set to "1" to skip DNS registration
#   EXTRA_PIP_PACKAGES – Space-separated extra pip packages to install
#   EXTRA_APT_PACKAGES – Space-separated extra apt packages to install
#   ENV_FILE_VARS      – Space-separated list of env var names to write
#                        into .env (fallback when no .env.template exists)
#                        e.g. "GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET"

log() { echo "[smart-launcher] $(date '+%H:%M:%S') $*"; }

# ──────────────────────────────────────────────
# 0. Validate required environment variables
# ──────────────────────────────────────────────
if [[ -z "${GITHUB_REPO:-}" ]]; then
    log "ERROR: GITHUB_REPO is required (e.g. https://github.com/user/my-app.git)"
    exit 1
fi
if [[ -z "${APP_NAME:-}" ]]; then
    log "ERROR: APP_NAME is required (the Reflex app module name)"
    exit 1
fi

GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
GITHUB_COMMIT="${GITHUB_COMMIT:-}"
GITHUB_SUBDIR="${GITHUB_SUBDIR:-}"
SERVICE_SUBDOMAIN="${SERVICE_SUBDOMAIN:-$APP_NAME}"
SERVICE_ZONE="${SERVICE_ZONE:-reflex-ddns.com}"
RE_DDNS_API_URL="${RE_DDNS_API_URL:-http://re-ddns:8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
SKIP_DNS_REGISTER="${SKIP_DNS_REGISTER:-0}"

log "=== Smart Launcher Configuration ==="
log "  GITHUB_REPO:       $GITHUB_REPO"
log "  GITHUB_BRANCH:     $GITHUB_BRANCH"
[[ -n "$GITHUB_COMMIT" ]] && log "  GITHUB_COMMIT:     $GITHUB_COMMIT"
log "  GITHUB_SUBDIR:     ${GITHUB_SUBDIR:-(root)}"
log "  APP_NAME:          $APP_NAME"
log "  SERVICE_SUBDOMAIN: $SERVICE_SUBDOMAIN"
log "  SERVICE_ZONE:      $SERVICE_ZONE"
log "  FRONTEND_PORT:     $FRONTEND_PORT"
log "  BACKEND_PORT:      $BACKEND_PORT"
log "=================================="

# ──────────────────────────────────────────────
# 1. Install extra APT packages (if any)
# ──────────────────────────────────────────────
if [[ -n "${EXTRA_APT_PACKAGES:-}" ]]; then
    log "Installing extra APT packages: $EXTRA_APT_PACKAGES"
    apt-get update && apt-get install -y --no-install-recommends $EXTRA_APT_PACKAGES \
        && apt-get clean && rm -rf /var/lib/apt/lists/*
fi

# ──────────────────────────────────────────────
# 2. Clone the GitHub repository
# ──────────────────────────────────────────────
CLONE_DIR="/app/source"

# Clean previous clone (handles container restarts)
if [[ -d "$CLONE_DIR" ]]; then
    log "Removing previous clone ..."
    rm -rf "$CLONE_DIR"
fi

log "Cloning $GITHUB_REPO (branch: $GITHUB_BRANCH) ..."
if [[ -n "$GITHUB_COMMIT" ]]; then
    # Need full history to checkout a specific commit
    git clone --branch "$GITHUB_BRANCH" "$GITHUB_REPO" "$CLONE_DIR"
    cd "$CLONE_DIR"
    log "Checking out commit: $GITHUB_COMMIT ..."
    git checkout "$GITHUB_COMMIT"
    cd /app
else
    git clone --depth 1 --branch "$GITHUB_BRANCH" "$GITHUB_REPO" "$CLONE_DIR"
fi

# Navigate to the project directory
PROJECT_DIR="$CLONE_DIR"
if [[ -n "$GITHUB_SUBDIR" ]]; then
    PROJECT_DIR="$CLONE_DIR/$GITHUB_SUBDIR"
    if [[ ! -d "$PROJECT_DIR" ]]; then
        log "ERROR: Subdirectory '$GITHUB_SUBDIR' not found in cloned repo"
        ls -la "$CLONE_DIR"
        exit 1
    fi
fi

cd "$PROJECT_DIR"
log "Working directory: $(pwd)"

# ──────────────────────────────────────────────
# 2.1 Install project-specific APT packages
# ──────────────────────────────────────────────
# If the cloned project ships an apt-packages.txt (one package name per line),
# install those system libraries now.  This lets each project declare its own
# native dependencies (e.g. WeasyPrint needs Pango/Cairo) without bloating
# the base Docker image.
if [[ -f "apt-packages.txt" ]]; then
    # Strip comments (#…) and blank lines
    _pkgs=$(grep -v '^\s*#' apt-packages.txt | grep -v '^\s*$' | tr '\n' ' ' || true)
    if [[ -n "$_pkgs" ]]; then
        log "Installing project APT packages from apt-packages.txt: $_pkgs"
        apt-get update && apt-get install -y --no-install-recommends $_pkgs \
            && apt-get clean && rm -rf /var/lib/apt/lists/*
    fi
fi

# ──────────────────────────────────────────────
# 2.1.1 Record installed APT packages for registry
# ──────────────────────────────────────────────
# Pass the package list to register_dns.py so it can be stored in
# registry.json as a deployment record (purely informational).
if [[ -f "apt-packages.txt" ]]; then
    _apt_record=$(grep -v '^\s*#' apt-packages.txt | grep -v '^\s*$' | tr '\n' ',' || true)
    _apt_record="${_apt_record%,}"  # trim trailing comma
    if [[ -n "$_apt_record" ]]; then
        export EXTRA_APT_PACKAGES="$_apt_record"
        log "APT packages for registry record: $EXTRA_APT_PACKAGES"
    fi
fi

# ──────────────────────────────────────────────
# 2.2 Read project-specific backend paths
# ──────────────────────────────────────────────
# If the project ships a backend-paths.txt (one URL path per line),
# these paths will be proxied to the backend port by nginx instead of
# the frontend.  This lets each project declare its own backend routes
# (e.g. /__embed, /yjs/) without hardcoding them in re_ddns.
if [[ -f "backend-paths.txt" ]]; then
    _paths=$(grep -v '^\s*#' backend-paths.txt | grep -v '^\s*$' | tr '\n' ',' || true)
    _paths="${_paths%,}"  # trim trailing comma
    if [[ -n "$_paths" ]]; then
        export EXTRA_BACKEND_PATHS="$_paths"
        log "Extra backend paths from backend-paths.txt: $EXTRA_BACKEND_PATHS"
    fi
fi

# ──────────────────────────────────────────────
# 2.5 Inject .env file
# ──────────────────────────────────────────────
# Priority:
#   1. /app/injected.env (mounted by smart_launch.sh via -v)
#   2. .env.template in the repo (copy as-is)
#   3. No .env → create empty so load_dotenv() won't error
if [[ -f "/app/injected.env" ]]; then
    cp /app/injected.env .env
    log "Using injected .env file (mounted from host)"
elif [[ -f ".env.template" && ! -f ".env" ]]; then
    cp .env.template .env
    log "Created .env from .env.template"
elif [[ ! -f ".env" ]]; then
    touch .env
    log "Created empty .env"
fi

# ──────────────────────────────────────────────
# 3. Generate / patch rxconfig.py
# ──────────────────────────────────────────────
# The key fix: inject api_url so Reflex generates the correct WebSocket URL in
# env.json.  Without this, the frontend tries ws://localhost:8000/_event which
# fails when accessed via https://<subdomain>.<zone>.
EXTERNAL_URL="https://${SERVICE_SUBDOMAIN}.${SERVICE_ZONE}"

if [[ -f "rxconfig.py" ]]; then
    log "Found existing rxconfig.py — patching api_url ..."
    # If api_url is already set, replace it; otherwise inject it after app_name
    if grep -q 'api_url' rxconfig.py; then
        sed -i "s|api_url=.*|api_url=\"${EXTERNAL_URL}\",|" rxconfig.py
    else
        # Insert api_url right after the app_name line
        sed -i "/app_name=/a\\        api_url=\"${EXTERNAL_URL}\"," rxconfig.py
    fi
    cat rxconfig.py
else
    log "No rxconfig.py found — creating one for app '$APP_NAME'"
    cat > rxconfig.py << PYEOF
import reflex as rx

config = rx.Config(
    app_name="${APP_NAME}",
    api_url="${EXTERNAL_URL}",
    plugins=[rx.plugins.TailwindV3Plugin()],
    cors_allowed_origins=["*"],
)
PYEOF
fi

# ──────────────────────────────────────────────
# 4. Install Python dependencies
# ──────────────────────────────────────────────
if [[ -f "pyproject.toml" ]]; then
    log "Installing dependencies with Poetry ..."
    # Ensure package-mode is off (some projects use [project] table without
    # [tool.poetry] name/version, which Poetry 1.x rejects in package mode).
    if ! grep -q 'package-mode' pyproject.toml; then
        # Add package-mode = false under [tool.poetry] (create section if needed)
        if grep -q '\[tool\.poetry\]' pyproject.toml; then
            sed -i '/\[tool\.poetry\]/a package-mode = false' pyproject.toml
        else
            printf '\n[tool.poetry]\npackage-mode = false\n' >> pyproject.toml
        fi
        log "Added package-mode = false to pyproject.toml"
    fi

    # Poetry 1.x ignores PEP 621 [project].dependencies — it only reads
    # [tool.poetry.dependencies]. Convert them if the project uses [project]
    # format and has no [tool.poetry.dependencies] section.
    if grep -q '^\[project\]' pyproject.toml && \
       ! grep -q '^\[tool\.poetry\.dependencies\]' pyproject.toml; then
        log "Converting [project].dependencies to [tool.poetry.dependencies] ..."
        python3 -c "
import re, sys

text = open('pyproject.toml').read()

# Extract dependencies from [project] section
m = re.search(r'dependencies\s*=\s*\[(.*?)\]', text, re.DOTALL)
if not m:
    sys.exit(0)

raw = m.group(1)
deps = []
for line in raw.split('\n'):
    line = line.strip().strip(',').strip('\"').strip(\"'\")
    if not line:
        continue
    # Parse 'reflex==0.8.25' or 'reflex>=0.8.23' or 'python-dotenv'
    match = re.match(r'^([a-zA-Z0-9_-]+)(.*)', line)
    if match:
        name = match.group(1)
        ver = match.group(2).strip()
        if ver:
            deps.append(f'{name} = \"{ver}\"')
        else:
            deps.append(f'{name} = \"*\"')

if deps:
    section = '\n[tool.poetry.dependencies]\npython = \">=3.11,<4.0\"\n'
    for d in deps:
        section += d + '\n'
    text += section
    open('pyproject.toml', 'w').write(text)
    print(f'Added {len(deps)} dependencies to [tool.poetry.dependencies]')
" 2>/dev/null || log "WARNING: dependency conversion had issues"
    fi

    # Remove stale lockfile from the cloned repo to avoid compatibility issues.
    rm -f poetry.lock
    log "Running poetry lock ..."
    poetry lock
    log "Running poetry install ..."
    poetry install --no-root
    log "Poetry install completed"
else
    log "No pyproject.toml found — creating a minimal one"
    cat > pyproject.toml << TOMLEOF
[project]
name = "${APP_NAME}"
version = "0.1.0"
requires-python = "~=3.11"

[tool.poetry]
package-mode = false

[tool.poetry.dependencies]
python = "~3.11"
reflex = "0.8.24.post1"
httpx = "*"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
TOMLEOF
    poetry install --no-root || (poetry lock && poetry install --no-root)
fi

# Install extra pip packages if specified
if [[ -n "${EXTRA_PIP_PACKAGES:-}" ]]; then
    log "Installing extra pip packages: $EXTRA_PIP_PACKAGES"
    poetry run pip install $EXTRA_PIP_PACKAGES
fi

# Ensure httpx is available (needed by register_dns.py)
poetry run python -c "import httpx" 2>/dev/null || poetry run pip install httpx

# ──────────────────────────────────────────────
# 4.5 Generate .env from .env.template if needed
# ──────────────────────────────────────────────
# Many Reflex apps use python-dotenv and expect a .env file.
# If the repo ships a .env.template but no .env, copy it as a starting point.
# Docker environment variables (set in docker-compose) will override .env values
# at runtime anyway.
if [[ ! -f ".env" && -f ".env.template" ]]; then
    cp .env.template .env
    log "Created .env from .env.template"
elif [[ ! -f ".env" ]]; then
    # Create an empty .env so load_dotenv() in rxconfig.py doesn't complain
    touch .env
    log "Created empty .env"
fi

# ──────────────────────────────────────────────
# 5. Initialize Reflex
# ──────────────────────────────────────────────
log "Running reflex init ..."
poetry run reflex init || true

# Patch Reflex Vite config template to allow any hostname
sed -i 's/port: process.env.PORT,/port: process.env.PORT,\n    allowedHosts: true,/' \
    .venv/lib/python3.11/site-packages/reflex/compiler/templates.py 2>/dev/null || true

# ──────────────────────────────────────────────
# 6. Register DNS record via re-ddns API
# ──────────────────────────────────────────────
if [[ "$SKIP_DNS_REGISTER" != "1" ]]; then
    log "Registering DNS record via re-ddns API ..."
    # Copy register_dns.py into the project if not present
    if [[ ! -f "register_dns.py" ]]; then
        cp /app/register_dns.py .
    fi
    poetry run python register_dns.py || log "WARNING: DNS registration failed — continuing anyway"
else
    log "Skipping DNS registration (SKIP_DNS_REGISTER=1)"
fi

# ──────────────────────────────────────────────
# 7. Patch Vite allowedHosts (runtime)
# ──────────────────────────────────────────────
VITE_CFG=".web/vite.config.js"
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
# 8. Create upload directory (common for Reflex apps)
# ──────────────────────────────────────────────
mkdir -p uploaded_files

# ──────────────────────────────────────────────
# 9. Export app-specific env vars & start Reflex
# ──────────────────────────────────────────────
# Tell apps (e.g. codoc_in_md) to use the external URL for backend
# requests generated in server-rendered HTML / JS, so remote browsers
# reach the backend through nginx instead of unreachable localhost:8000.
export CODOC_BACKEND_BASE_URL="${EXTERNAL_URL}"
log "CODOC_BACKEND_BASE_URL=${CODOC_BACKEND_BASE_URL}"

log "Starting Reflex dev server on ports $FRONTEND_PORT/$BACKEND_PORT ..."
exec poetry run reflex run \
    --env dev \
    --frontend-port "$FRONTEND_PORT" \
    --backend-port "$BACKEND_PORT" \
    --loglevel info
