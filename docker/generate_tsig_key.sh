#!/usr/bin/env bash
set -euo pipefail

# generate_tsig_key.sh
# ────────────────────
# Generates a TSIG key and patches the BIND9 config files.
# Run this ONCE before the first `docker compose up --build`.
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

# Patch named.conf.local
sed -i.bak "s|CHANGE_ME_GENERATE_WITH_TSIG_KEYGEN|$SECRET|g" "$SCRIPT_DIR/named.conf.local"
rm -f "$SCRIPT_DIR/named.conf.local.bak"

# Patch rndc.conf
sed -i.bak "s|CHANGE_ME_GENERATE_WITH_TSIG_KEYGEN|$SECRET|g" "$SCRIPT_DIR/rndc.conf"
rm -f "$SCRIPT_DIR/rndc.conf.bak"

echo "Updated:"
echo "  - $SCRIPT_DIR/named.conf.local"
echo "  - $SCRIPT_DIR/rndc.conf"
echo ""
echo "Use these values in the Reflex app's configuration form:"
echo "  Key Name:   $KEY_NAME"
echo "  Key Secret: $SECRET"
echo "  Server IP:  127.0.0.1  (inside Docker)"
echo ""
echo "Now run:"
echo "  docker compose up --build"
