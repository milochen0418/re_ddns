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
DOMAIN="reflex-ddns.com"
RESOLVER_DIR="/etc/resolver"
HOSTS_FILE="/etc/hosts"
HOSTS_MARKER="# re-ddns-managed"
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

# ── Helper: discover DHCP-provided DNS servers ───────────────────────────
# networksetup -getdnsservers only shows *manually* set DNS servers.
# When the user hasn't set any (DHCP mode), it returns nothing — but the
# system IS still using DHCP-provided nameservers.  We must discover those
# so we can keep them as fallbacks when prepending our local DNS.
dhcp_dns() {
    # 1. Find the BSD device name (e.g. en0) for the network service
    local device
    device=$(networksetup -listallhardwareports 2>/dev/null \
        | awk -v svc="$IFACE" '
            $0 ~ "Hardware Port: " svc { found=1; next }
            found && /^Device:/ { print $2; exit }
          ')

    if [[ -z "$device" ]]; then
        # Fallback: try scutil --dns resolver #1
        scutil --dns 2>/dev/null \
            | awk '/^resolver #1/,/^$/' \
            | awk '/nameserver\[/ { print $3 }' \
            | grep -v '%' \
            | tr '\n' ' ' | sed 's/ $//'
        return
    fi

    # 2. Ask ipconfig for the DHCP packet on that device
    local servers
    servers=$(ipconfig getpacket "$device" 2>/dev/null \
        | awk -F'[{},]' '/domain_name_server/ {
            for (i=2; i<=NF; i++) {
                gsub(/^[ \t]+|[ \t]+$/, "", $i)
                if ($i != "") print $i
            }
        }')

    if [[ -n "$servers" ]]; then
        echo "$servers" | tr '\n' ' ' | sed 's/ $//'
    else
        # 3. Last resort: scutil --dns resolver #1 (skip link-local/IPv6 with %)
        scutil --dns 2>/dev/null \
            | awk '/^resolver #1/,/^$/' \
            | awk '/nameserver\[/ { print $3 }' \
            | grep -v '%' \
            | tr '\n' ' ' | sed 's/ $//'
    fi
}

# ── Commands ──────────────────────────────────────────────────────────────
case "$CMD" in

  list)
    echo "Interface : $IFACE"
    servers=$(current_dns)
    if [[ -z "$servers" ]]; then
        dhcp_servers=$(dhcp_dns)
        if [[ -n "$dhcp_servers" ]]; then
            echo "DNS       : (DHCP-provided)"
            for s in $dhcp_servers; do
                echo "  $s  ← from DHCP"
            done
        else
            echo "DNS       : (none – no DHCP DNS found either)"
        fi
    else
        echo "DNS       : (manually set)"
        for s in $servers; do
            if [[ "$s" == "$LOCAL_DNS" ]]; then
                echo "  $s  ← local Docker BIND9"
            else
                echo "  $s"
            fi
        done
    fi
    # Show /etc/resolver status
    if [[ -f "$RESOLVER_DIR/$DOMAIN" ]]; then
        echo "Resolver  : $RESOLVER_DIR/$DOMAIN → $(cat "$RESOLVER_DIR/$DOMAIN" | awk '/nameserver/{print $2}')"
    else
        echo "Resolver  : $RESOLVER_DIR/$DOMAIN (not set)"
    fi
    # Show /etc/hosts entries
    if grep -q "$HOSTS_MARKER" "$HOSTS_FILE" 2>/dev/null; then
        echo "Hosts     : (managed entries found)"
        grep "$HOSTS_MARKER" "$HOSTS_FILE" | while read -r line; do
            echo "  $line"
        done
    else
        echo "Hosts     : (no managed entries)"
    fi
    ;;

  join)
    servers=$(current_dns)
    case " $servers " in
        *" $LOCAL_DNS "*)
            echo "[$IFACE] $LOCAL_DNS already in DNS list."
            ;;
        *)

    # If no manual DNS is set, discover DHCP-provided DNS so we can keep
    # them as fallbacks.  Without this, setting only 127.0.0.1 would make
    # macOS lose all DNS when the Docker container is down.
    if [[ -z "$servers" ]]; then
        dhcp_servers=$(dhcp_dns)
        if [[ -n "$dhcp_servers" ]]; then
            echo "[$IFACE] Discovered DHCP DNS: $dhcp_servers"
            servers="$dhcp_servers"
        fi
    fi

    # prepend local DNS so it is queried first, keep originals as fallback
    new_list="$LOCAL_DNS${servers:+ $servers}"
    echo "[$IFACE] Setting DNS list → $new_list"
    sudo networksetup -setdnsservers "$IFACE" $new_list
    echo "[$IFACE] New DNS list:"
    networksetup -getdnsservers "$IFACE"
            ;;
    esac

    # Create /etc/resolver entry so mDNSResponder routes *.reflex-ddns.com
    # queries to our local BIND9 (this is what curl/python/apps actually use).
    if [[ ! -f "$RESOLVER_DIR/$DOMAIN" ]]; then
        sudo mkdir -p "$RESOLVER_DIR"
        echo "nameserver $LOCAL_DNS" | sudo tee "$RESOLVER_DIR/$DOMAIN" > /dev/null
        echo "[$IFACE] Created $RESOLVER_DIR/$DOMAIN → $LOCAL_DNS"
    else
        echo "[$IFACE] $RESOLVER_DIR/$DOMAIN already exists."
    fi

    # Add /etc/hosts entries so Mac resolves *.reflex-ddns.com to 127.0.0.1
    # (BIND9 zone uses container IPs for inter-container routing, but Mac
    # accesses Docker via published ports on localhost)
    if ! grep -q "$HOSTS_MARKER" "$HOSTS_FILE" 2>/dev/null; then
        {
            echo "$LOCAL_DNS home.$DOMAIN  $HOSTS_MARKER"
        } | sudo tee -a "$HOSTS_FILE" > /dev/null
        echo "[$IFACE] Added *.${DOMAIN} entries to /etc/hosts → $LOCAL_DNS"
    else
        echo "[$IFACE] /etc/hosts entries already present"
    fi
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

    # Decide whether to revert to DHCP or keep the remaining servers.
    # If the remaining servers are exactly the DHCP-provided ones,
    # revert to DHCP mode so the system is back to its original state.
    should_revert_dhcp=false
    if [[ -z "$new_list" ]]; then
        should_revert_dhcp=true
    else
        dhcp_servers=$(dhcp_dns)
        # Sort and compare: if remaining == DHCP DNS, revert to DHCP
        remaining_sorted=$(echo "$new_list" | tr ' ' '\n' | sort)
        dhcp_sorted=$(echo "$dhcp_servers" | tr ' ' '\n' | sort)
        if [[ "$remaining_sorted" == "$dhcp_sorted" ]]; then
            should_revert_dhcp=true
        fi
    fi

    if $should_revert_dhcp; then
        sudo networksetup -setdnsservers "$IFACE" "Empty"
        echo "[$IFACE] Reverted to DHCP-provided DNS."
    else
        sudo networksetup -setdnsservers "$IFACE" $new_list
        echo "[$IFACE] New DNS list:"
        networksetup -getdnsservers "$IFACE"
    fi
    # Remove /etc/resolver entry
    if [[ -f "$RESOLVER_DIR/$DOMAIN" ]]; then
        sudo rm -f "$RESOLVER_DIR/$DOMAIN"
        echo "[$IFACE] Removed $RESOLVER_DIR/$DOMAIN"
    fi
    # Remove /etc/hosts entries
    if grep -q "$HOSTS_MARKER" "$HOSTS_FILE" 2>/dev/null; then
        sudo sed -i '' "/$HOSTS_MARKER/d" "$HOSTS_FILE"
        echo "[$IFACE] Removed managed entries from /etc/hosts"
    fi
    # Flush macOS DNS cache
    sudo dscacheutil -flushcache
    sudo killall -HUP mDNSResponder 2>/dev/null || true
    echo "DNS cache flushed."
    ;;

esac
