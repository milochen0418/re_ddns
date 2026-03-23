#!/bin/bash
# Install Re-DDNS Root CA **and** configure DNS on a remote macOS machine via SSH.
#
# What it does:
#   1. Copies ca.pem to the remote Mac and installs it as a trusted root cert.
#   2. Copies macos_set_dns.sh to the remote Mac and runs --join with --dns
#      pointing to THIS machine's IP, so the remote Mac uses our BIND9.
#
# Usage:
#   ./remote_install_ca.sh [user@host]
#
# Default target: milochen@172.20.10.2

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Help ──────────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: ./remote_install_ca.sh [OPTIONS] [user@host]

Configure a remote macOS machine to work with Re-DDNS by installing the
CA certificate and setting up DNS — all in one step, over SSH.

Arguments:
  user@host       SSH target (default: milochen@172.20.10.2)

Options:
  --help, -h      Show this help message and exit

What this script does:
  Step 1  Check SSH connectivity to the remote Mac.
  Step 2  Download the Re-DDNS Root CA from the local server, copy it to the
          remote Mac via scp, and install it as a trusted root certificate
          in the System Keychain.
  Step 3  Copy macos_set_dns.sh to the remote Mac and run it with
          --join --dns <this-Mac-IP>, so the remote Mac's DNS queries for
          *.reflex-ddns.com are forwarded to this Mac's Docker BIND9.
          This also creates /etc/resolver/reflex-ddns.com and /etc/hosts
          entries on the remote Mac.
  Step 4  Verify DNS resolution from the remote Mac using nslookup.

Prerequisites:
  1. SSH key-based login must be configured. If not yet done, run:

         ssh-copy-id milochen@172.20.10.2

     This copies your public key to the remote Mac so that ssh/scp
     commands can run without a password prompt (sudo will still ask).
     If you don't have an SSH key yet, generate one first:

         ssh-keygen -t ed25519

  2. Docker must be running on THIS Mac with the Re-DDNS stack up:

         ./docker_restart.sh          # start the Docker stack
         ./macos_set_dns.sh --join    # configure local DNS (if not done)

  3. The remote Mac should be reachable on the same network.

Examples:
  # Default target (milochen@172.20.10.2):
  ./remote_install_ca.sh

  # Specify a different remote Mac:
  ./remote_install_ca.sh john@192.168.1.50

  # To undo DNS changes on the remote Mac later:
  ssh -t milochen@172.20.10.2 'bash -s' < macos_set_dns.sh --leave

After completion:
  • Restart the browser on the remote Mac for the CA to take effect.
  • The remote Mac can now browse https://home.reflex-ddns.com and other
    *.reflex-ddns.com HTTPS sites without certificate warnings.
EOF
}

# ── Parse arguments ───────────────────────────────────────────────────────
REMOTE=""
for arg in "$@"; do
    case "$arg" in
        --help|-h) usage; exit 0 ;;
        *)         REMOTE="$arg" ;;
    esac
done
REMOTE="${REMOTE:-milochen@172.20.10.2}"
CA_NAME="Re-DDNS Root CA"
KEYCHAIN="/Library/Keychains/System.keychain"
TMP_PEM="/tmp/re_ddns_ca.pem"
DOWNLOAD_URL="http://home.reflex-ddns.com/api/ca.pem"
LOCAL_PEM="/tmp/re_ddns_ca_local.pem"

# ── Detect this Mac's IP on the same subnet as the remote host ──
REMOTE_HOST="${REMOTE#*@}"
detect_local_ip() {
    # Find the local IP that can route to the remote host
    local ip
    ip=$(ipconfig getifaddr en0 2>/dev/null || true)
    if [[ -z "$ip" ]]; then
        ip=$(route get "$REMOTE_HOST" 2>/dev/null | awk '/interface:/{iface=$2} /source:/{print $2}' | tail -1)
    fi
    echo "$ip"
}

LOCAL_IP=$(detect_local_ip)
if [[ -z "$LOCAL_IP" ]]; then
    echo "ERROR: Cannot determine local IP address. Please check your network."
    exit 1
fi

echo "==> Local IP : $LOCAL_IP"
echo "==> Target   : $REMOTE"

# ── 1. SSH connectivity check ──
echo ""
echo "==> [Step 1/4] Checking SSH connectivity..."
ssh -o ConnectTimeout=5 "$REMOTE" 'echo "SSH OK: $(hostname)"' || {
    echo "ERROR: Cannot reach $REMOTE via SSH."
    exit 1
}

# ── 2. Install CA certificate ──
echo ""
echo "==> [Step 2/4] Installing CA certificate..."

echo "    Downloading CA certificate locally..."
curl -fsSL -o "$LOCAL_PEM" "$DOWNLOAD_URL" || {
    echo "ERROR: Failed to download CA from $DOWNLOAD_URL on local machine."
    exit 1
}

echo "    Copying CA certificate to remote host..."
scp "$LOCAL_PEM" "$REMOTE:$TMP_PEM" || {
    echo "ERROR: Failed to copy CA to $REMOTE."
    exit 1
}
rm -f "$LOCAL_PEM"

echo "    Checking current CA status on remote host..."
INSTALLED=$(ssh "$REMOTE" "security find-certificate -c '$CA_NAME' '$KEYCHAIN' >/dev/null 2>&1 && echo 1 || echo 0")

if [ "$INSTALLED" = "1" ]; then
    echo "    CA already installed — removing old cert first."
    ssh -t "$REMOTE" bash -c "'
        CERT_SHA1=\$(security find-certificate -c \"$CA_NAME\" -Z \"$KEYCHAIN\" 2>/dev/null | awk \"/SHA-1 hash:/{print \\\$NF}\")
        if [ -n \"\$CERT_SHA1\" ]; then
            sudo security delete-certificate -Z \"\$CERT_SHA1\" \"$KEYCHAIN\"
            echo \"    Old certificate removed.\"
        fi
    '"
fi

echo "    Installing CA certificate as trusted root..."
ssh -t "$REMOTE" "sudo security add-trusted-cert -d -r trustRoot -k '$KEYCHAIN' '$TMP_PEM'" || {
    echo "ERROR: Failed to install CA on remote host."
    exit 1
}

ssh "$REMOTE" "rm -f '$TMP_PEM'"
echo "    ✅ CA certificate installed."

# ── 3. Configure DNS via macos_set_dns.sh ──
echo ""
echo "==> [Step 3/4] Configuring DNS on remote host (dns=$LOCAL_IP)..."

DNS_SCRIPT="$SCRIPT_DIR/macos_set_dns.sh"
if [[ ! -f "$DNS_SCRIPT" ]]; then
    echo "ERROR: macos_set_dns.sh not found at $DNS_SCRIPT"
    exit 1
fi

REMOTE_DNS_SCRIPT="/tmp/macos_set_dns.sh"
scp "$DNS_SCRIPT" "$REMOTE:$REMOTE_DNS_SCRIPT" || {
    echo "ERROR: Failed to copy macos_set_dns.sh to $REMOTE."
    exit 1
}

ssh -t "$REMOTE" "chmod +x '$REMOTE_DNS_SCRIPT' && bash '$REMOTE_DNS_SCRIPT' --join --dns '$LOCAL_IP'" || {
    echo "ERROR: Failed to configure DNS on remote host."
    exit 1
}

ssh "$REMOTE" "rm -f '$REMOTE_DNS_SCRIPT'"
echo "    ✅ DNS configured."

# ── 4. Verify ──
echo ""
echo "==> [Step 4/4] Verifying from remote host..."
ssh "$REMOTE" "nslookup home.reflex-ddns.com '$LOCAL_IP' 2>&1 | head -6" || true

echo ""
echo "════════════════════════════════════════════════════════"
echo "✅  Remote Mac ($REMOTE) is fully configured:"
echo "    • Re-DDNS Root CA installed and trusted"
echo "    • DNS points to $LOCAL_IP (this Mac's BIND9)"
echo "    • Please restart the browser on the remote Mac."
echo "════════════════════════════════════════════════════════"
