#!/usr/bin/env bash
# macos_set_dns.sh
# ────────────────
# Manage macOS Wi-Fi DNS to include / exclude the local Docker BIND9.
#
# Usage:
#   ./macos_set_dns.sh --list           # show current DNS servers
#   ./macos_set_dns.sh --join           # prepend 127.0.0.1 to DNS list
#   ./macos_set_dns.sh --leave          # remove 127.0.0.1 from DNS list
#
# Optional flags:
#   --iface <name>   Network interface (default: Wi-Fi)
#   --dns   <ip>     DNS server to add/remove (default: 127.0.0.1)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────
IFACE="Wi-Fi"
LOCAL_DNS="127.0.0.1"
CMD=""

# ── Parse arguments ────────────────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $(basename "$0") COMMAND [OPTIONS]

Manage macOS DNS servers to include or exclude the local Docker BIND9.

Commands:
  --list    Show the current DNS servers for the network interface.
            Highlights entries that match the local Docker DNS IP.

  --join    Prepend the local Docker DNS (default: 127.0.0.1) to the
            DNS list so it is queried first.
            Requires sudo. Flushes the macOS DNS cache afterwards.

  --leave   Remove the local Docker DNS from the DNS list.
            If it was the only entry, reverts to DHCP-provided DNS.
            Requires sudo. Flushes the macOS DNS cache afterwards.

  --help    Show this help message and exit.

Options:
  --iface <name>   Network interface to configure (default: Wi-Fi).
                   Run 'networksetup -listallnetworkservices' to list
                   available interfaces.

  --dns <ip>       The DNS server IP to add or remove (default: 127.0.0.1).

Examples:
  $(basename "$0") --list
  $(basename "$0") --join
  $(basename "$0") --leave
  $(basename "$0") --join  --iface Ethernet
  $(basename "$0") --leave --dns 192.168.1.1 --iface "USB 10/100/1000 LAN"

Notes:
  • --join and --leave both require sudo to modify network settings.
  • macOS DNS cache is flushed automatically on --join and --leave.
  • This script only modifies the DNS list; it does not start or stop Docker.
  • To verify the change took effect:
      scutil --dns | grep nameserver
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)   CMD="list"  ; shift ;;
        --join)   CMD="join"  ; shift ;;
        --leave)  CMD="leave" ; shift ;;
        --help)   usage; exit 0 ;;
        --iface)  IFACE="$2"  ; shift 2 ;;
        --dns)    LOCAL_DNS="$2" ; shift 2 ;;
        *) echo "Unknown option: $1"; echo "Run '$(basename "$0") --help' for usage."; exit 1 ;;
    esac
done

if [[ -z "$CMD" ]]; then
    usage
    exit 1
fi

# ── Helper: get current DNS list as space-separated string ────────────────
current_dns() {
    local result
    result=$(networksetup -getdnsservers "$IFACE" 2>/dev/null) || true
    # If no DNS servers are set, networksetup prints a human-readable message
    case "$result" in
        *"aren't any"*|*"There aren't"*|"")
            echo ""
            return 0
            ;;
    esac
    # one server per line → space-separated
    echo "$result" | tr '\n' ' ' | sed 's/[[:space:]]*$//'
}

# ── Commands ──────────────────────────────────────────────────────────────
case "$CMD" in

  list)
    echo "Interface : $IFACE"
    servers=$(current_dns)
    if [[ -z "$servers" ]]; then
        echo "DNS       : (none – using DHCP-provided DNS)"
    else
        echo "DNS       :"
        for s in $servers; do
            if [[ "$s" == "$LOCAL_DNS" ]]; then
                echo "  $s  ← local Docker BIND9"
            else
                echo "  $s"
            fi
        done
    fi
    ;;

  join)
    servers=$(current_dns)
    case " $servers " in
        *" $LOCAL_DNS "*)
            echo "[$IFACE] $LOCAL_DNS already in DNS list. Nothing to do."
            exit 0
            ;;
    esac
    # prepend local DNS so it is queried first
    new_list="$LOCAL_DNS${servers:+ $servers}"
    echo "[$IFACE] Adding $LOCAL_DNS to DNS list …"
    sudo networksetup -setdnsservers "$IFACE" $new_list
    echo "[$IFACE] New DNS list:"
    networksetup -getdnsservers "$IFACE"
    # Flush macOS DNS cache
    sudo dscacheutil -flushcache
    sudo killall -HUP mDNSResponder 2>/dev/null || true
    echo "DNS cache flushed."
    ;;

  leave)
    servers=$(current_dns)
    case " $servers " in
        *" $LOCAL_DNS "*) : ;;  # found, continue
        *)
            echo "[$IFACE] $LOCAL_DNS not in DNS list. Nothing to do."
            exit 0
            ;;
    esac
    # Remove LOCAL_DNS from the list
    new_list=$(echo "$servers" | tr ' ' '\n' | grep -v "^${LOCAL_DNS}$" | tr '\n' ' ' | sed 's/ $//' || true)
    echo "[$IFACE] Removing $LOCAL_DNS from DNS list …"
    if [[ -z "$new_list" ]]; then
        # No servers left → revert to DHCP
        sudo networksetup -setdnsservers "$IFACE" "Empty"
        echo "[$IFACE] Reverted to DHCP-provided DNS."
    else
        sudo networksetup -setdnsservers "$IFACE" $new_list
        echo "[$IFACE] New DNS list:"
        networksetup -getdnsservers "$IFACE"
    fi
    # Flush macOS DNS cache
    sudo dscacheutil -flushcache
    sudo killall -HUP mDNSResponder 2>/dev/null || true
    echo "DNS cache flushed."
    ;;

esac
