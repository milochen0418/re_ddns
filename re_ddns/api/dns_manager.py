"""DNS record manager — RFC 2136 dynamic updates via TSIG.

This module handles the low-level DNS operations (creating / replacing
records on a BIND9 server using TSIG authentication).  It is called
by ``registry_api`` after the registry JSON has been updated.

Supported record types: A, AAAA, CNAME, MX, TXT, NS, SRV, PTR, CAA.

It does **not** own any FastAPI routes or state — it is a pure helper.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import dns.query
import dns.rcode
import dns.rdatatype
import dns.tsigkeyring
import dns.update

logger = logging.getLogger(__name__)


# Supported record types and their rdata format descriptions
SUPPORTED_TYPES = {
    "A":     "IPv4 address (e.g. 192.168.1.1)",
    "AAAA":  "IPv6 address (e.g. 2001:db8::1)",
    "CNAME": "Canonical name (e.g. www.example.com.)",
    "MX":    "Priority + mail server (e.g. 10 mail.example.com.)",
    "TXT":   "Text string (e.g. \"v=spf1 +a ~all\")",
    "NS":    "Nameserver (e.g. ns1.example.com.)",
    "SRV":   "Priority Weight Port Target (e.g. 10 60 5060 sip.example.com.)",
    "PTR":   "Pointer (e.g. host.example.com.)",
    "CAA":   "Flag Tag Value (e.g. 0 issue \"letsencrypt.org\")",
}


# ---------------------------------------------------------------------------
# TSIG credentials (read once from env-file written by entrypoint.sh)
# ---------------------------------------------------------------------------

def _read_tsig_defaults() -> dict[str, str]:
    """Return TSIG defaults from the env-file written by entrypoint.sh."""
    path = "/etc/bind/tsig-secret.env"
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                result[k] = v
    except Exception:
        pass
    return result


_tsig = _read_tsig_defaults()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def do_dns_update(
    record_name: str,
    zone_name: str,
    rdata: str,
    ttl: int,
    *,
    record_type: str = "A",
    key_name: Optional[str] = None,
    key_secret: Optional[str] = None,
    server_ip: str = "127.0.0.1",
) -> tuple[bool, str]:
    """Perform an RFC 2136 DNS update.

    *rdata* is the record-type-specific data string:
      - A/AAAA: IP address
      - CNAME/NS/PTR: hostname
      - MX: "priority hostname"
      - TXT: quoted text
      - SRV: "priority weight port target"
      - CAA: "flag tag value"

    If *key_name* / *key_secret* are not provided, server-side TSIG
    defaults are used.

    Returns ``(success: bool, message: str)``.
    """
    key_name = key_name or _tsig.get("TSIG_KEY_NAME", "")
    key_secret = key_secret or _tsig.get("TSIG_SECRET", "")
    if not key_name or not key_secret:
        return False, "No server-side TSIG credentials available."

    if record_type not in SUPPORTED_TYPES:
        return False, f"Unsupported record type: {record_type}"

    try:
        keyring = dns.tsigkeyring.from_text({key_name: key_secret})
        update = dns.update.Update(zone_name, keyring=keyring)
        update.replace(record_name, ttl, record_type, rdata)
        response = dns.query.tcp(update, server_ip, timeout=10.0)
        rcode_val = response.rcode()
        if rcode_val != dns.rcode.NOERROR:
            return False, f"DNS RCODE: {dns.rcode.to_text(rcode_val)}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def do_dns_delete(
    record_name: str,
    zone_name: str,
    *,
    record_type: str = "A",
    key_name: Optional[str] = None,
    key_secret: Optional[str] = None,
    server_ip: str = "127.0.0.1",
) -> tuple[bool, str]:
    """Delete a DNS record via RFC 2136.

    Returns ``(success: bool, message: str)``.
    """
    key_name = key_name or _tsig.get("TSIG_KEY_NAME", "")
    key_secret = key_secret or _tsig.get("TSIG_SECRET", "")
    if not key_name or not key_secret:
        return False, "No server-side TSIG credentials available."

    try:
        keyring = dns.tsigkeyring.from_text({key_name: key_secret})
        update = dns.update.Update(zone_name, keyring=keyring)
        update.delete(record_name, record_type)
        response = dns.query.tcp(update, server_ip, timeout=10.0)
        rcode_val = response.rcode()
        if rcode_val != dns.rcode.NOERROR:
            return False, f"DNS RCODE: {dns.rcode.to_text(rcode_val)}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
