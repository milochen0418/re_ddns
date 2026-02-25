#!/usr/bin/env bash
set -euo pipefail

# generate_tsig_key.sh
# ────────────────────
# [OPTIONAL] Pre-seed a fixed TSIG key into the BIND9 config templates.
#
# ┌─ You normally do NOT need this script ─────────────────────────────────┐
# │ entrypoint.sh auto-generates a random TSIG key at container startup     │
# │ and injects it into /etc/bind/named.conf.local and /etc/bind/rndc.conf. │
# │ The generated key is also written to /etc/bind/tsig-secret.env.         │
# │                                                                          │
# │ Run this script only when you want a known, persistent key baked into   │
# │ the image (e.g. CI, GitOps, or you prefer not to use TSIG_SECRET env).  │
# │                                                                          │
# │ Alternative (runtime only, no image baking):                            │
# │   Set TSIG_SECRET=<base64> in docker-compose.yml environment section.   │
# └──────────────────────────────────────────────────────────────────────────┘
#
# Usage:
#   ./docker/generate_tsig_key.sh [key-name]
#
# Default key name: ddns-key

KEY_NAME="${1:-ddns-key}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Generating TSIG key: $KEY_NAME (hmac-sha256) …"

# Generate a random 256-bit key (base64)
SECRET=$(python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())")

echo ""
echo "┌──────────────────────────────────────────┐"
echo "│  TSIG Key Generated                      │"
echo "├──────────────────────────────────────────┤"
echo "│  Name:   $KEY_NAME"
echo "│  Secret: $SECRET"
echo "└──────────────────────────────────────────┘"
echo ""

# Patch named.conf.local.template (named.conf.local is gitignored / runtime only)
sed -i.bak "s|__TSIG_SECRET__|$SECRET|g" "$SCRIPT_DIR/named.conf.local.template"
rm -f "$SCRIPT_DIR/named.conf.local.template.bak"

# Patch rndc.conf
sed -i.bak "s|__TSIG_SECRET__|$SECRET|g" "$SCRIPT_DIR/rndc.conf"
rm -f "$SCRIPT_DIR/rndc.conf.bak"

echo "Updated (placeholder __TSIG_SECRET__ replaced in template files):"
echo "  - $SCRIPT_DIR/named.conf.local.template"
echo "  - $SCRIPT_DIR/rndc.conf"
echo ""
echo "The key is now baked into the config templates."
echo "Alternatively, pass it at runtime (no need to run this script):"
echo "  TSIG_SECRET=$SECRET docker compose up --build"
echo ""
echo "Use these values in the Reflex app's configuration form:"
echo "  Key Name:   $KEY_NAME"
echo "  Key Secret: $SECRET"
echo "  Server IP:  127.0.0.1  (inside Docker)"
echo ""
echo "Now run:"
echo "  docker compose up --build"
