"""DNS record manager — RFC 2136 dynamic updates via TSIG.

This module handles the low-level DNS operations (creating / replacing
A records on a BIND9 server using TSIG authentication).  It is called
by ``registry_api`` after the registry JSON has been updated.

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
    ip_address: str,
    ttl: int,
    *,
    record_type: str = "A",
    key_name: Optional[str] = None,
    key_secret: Optional[str] = None,
    server_ip: str = "127.0.0.1",
) -> tuple[bool, str]:
    """Perform an RFC 2136 DNS update.

    If *key_name* / *key_secret* are not provided, server-side TSIG
    defaults are used.

    Returns ``(success: bool, message: str)``.
    """
    key_name = key_name or _tsig.get("TSIG_KEY_NAME", "")
    key_secret = key_secret or _tsig.get("TSIG_SECRET", "")
    if not key_name or not key_secret:
        return False, "No server-side TSIG credentials available."

    try:
        keyring = dns.tsigkeyring.from_text({key_name: key_secret})
        update = dns.update.Update(zone_name, keyring=keyring)
        update.replace(record_name, ttl, record_type, ip_address)
        response = dns.query.tcp(update, server_ip, timeout=10.0)
        rcode_val = response.rcode()
        if rcode_val != dns.rcode.NOERROR:
            return False, f"DNS RCODE: {dns.rcode.to_text(rcode_val)}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
