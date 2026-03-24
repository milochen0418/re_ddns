#!/usr/bin/env bash
# ── detect_external_ip.sh ──
#
# Shared helper: detect or let the user choose the LAN IP for EXTERNAL_IP.
#
# Usage (source from another script):
#   source "$(dirname "$0")/detect_external_ip.sh"
#   # After sourcing, EXTERNAL_IP is exported.
#
# Behaviour:
#   1. If EXTERNAL_IP is already set in the environment → keep it.
#   2. Collect all non-loopback IPv4 addresses on active interfaces.
#   3. If exactly one IP is found → use it automatically.
#   4. If multiple IPs are found → prompt the user to choose (interactive)
#      or fall back to the first one (non-interactive / piped stdin).
#   5. If no IP is found → fall back to 127.0.0.1.

_detect_external_ip() {
    # Ensure 0-based arrays (zsh uses 1-based by default)
    if [[ -n "${ZSH_VERSION:-}" ]]; then setopt localoptions KSH_ARRAYS; fi

    # Already set by caller → nothing to do
    if [[ -n "${EXTERNAL_IP:-}" ]]; then
        return
    fi

    local _ips=()
    local _labels=()
    local _ip _iface _line

    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: iterate network device interfaces
        while IFS= read -r _iface; do
            _ip=$(ipconfig getifaddr "$_iface" 2>/dev/null) || true
            if [[ -n "$_ip" && "$_ip" != 127.* ]]; then
                _ips+=("$_ip")
                _labels+=("$_ip  ($_iface)")
            fi
        done < <(networksetup -listallhardwareports 2>/dev/null \
                 | awk '/^Device:/{print $2}')

        # Fallback: try common interfaces if networksetup found nothing
        if [[ ${#_ips[@]} -eq 0 ]]; then
            for _iface in en0 en1 en2 en3; do
                _ip=$(ipconfig getifaddr "$_iface" 2>/dev/null) || true
                if [[ -n "$_ip" && "$_ip" != 127.* ]]; then
                    _ips+=("$_ip")
                    _labels+=("$_ip  ($_iface)")
                fi
            done
        fi
    else
        # Linux
        while IFS= read -r _line; do
            _ip=$(echo "$_line"  | awk '{print $1}')
            _iface=$(echo "$_line" | awk '{print $2}')
            if [[ -n "$_ip" && "$_ip" != 127.* ]]; then
                _ips+=("$_ip")
                _labels+=("$_ip  ($_iface)")
            fi
        done < <(ip -4 -o addr show scope global 2>/dev/null \
                 | awk '{gsub(/\/.*/, "", $4); print $4, $2}')
    fi

    # Deduplicate (preserve order)
    local _unique_ips=()
    local _unique_labels=()
    local _seen=""
    local _i
    local _n=${#_ips[@]}
    for (( _i=0; _i<_n; _i++ )); do
        if [[ ":$_seen:" != *":${_ips[$_i]}:"* ]]; then
            _unique_ips+=("${_ips[$_i]}")
            _unique_labels+=("${_labels[$_i]}")
            _seen="$_seen:${_ips[$_i]}"
        fi
    done
    _ips=("${_unique_ips[@]}")
    _labels=("${_unique_labels[@]}")

    local _count=${#_ips[@]}

    if [[ $_count -eq 0 ]]; then
        EXTERNAL_IP="127.0.0.1"
    elif [[ $_count -eq 1 ]]; then
        EXTERNAL_IP="${_ips[0]}"
    else
        # Multiple IPs – let the user pick (if interactive)
        if [[ -t 0 ]]; then
            echo ""
            echo "Multiple network interfaces detected:"
            for (( _i=0; _i<_count; _i++ )); do
                echo "  $((_i+1))) ${_labels[$_i]}"
            done
            echo ""
            local _choice
            read -r -p "Select EXTERNAL_IP [1-${_count}, default=1]: " _choice
            _choice="${_choice:-1}"
            if [[ "$_choice" =~ ^[0-9]+$ ]] && (( _choice >= 1 && _choice <= _count )); then
                EXTERNAL_IP="${_ips[$((_choice-1))]}"
            else
                echo "Invalid choice, using ${_ips[0]}"
                EXTERNAL_IP="${_ips[0]}"
            fi
        else
            # Non-interactive: pick the first one
            EXTERNAL_IP="${_ips[0]}"
        fi
    fi
}

_detect_external_ip
export EXTERNAL_IP
