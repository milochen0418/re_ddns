"""State for the Advanced DNS page.

Supports all common DNS record types with dynamic form fields:
  A, AAAA, CNAME, MX, TXT, NS, SRV, PTR, CAA

Uses dns_manager.do_dns_update() for the actual RFC 2136 update,
which handles TSIG authentication and BIND9 communication.
"""

import reflex as rx
import re
import os
import httpx


def _read_tsig_env_file(path: str = "/etc/bind/tsig-secret.env") -> dict[str, str]:
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


_tsig_defaults = _read_tsig_env_file()

# Record types and which fields they need
_RECORD_TYPE_OPTIONS: list[str] = [
    "A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "PTR", "CAA",
]


class AdvancedDNSState(rx.State):
    """Manages the Advanced DNS page state."""

    # Server connection
    server_ip: str = "127.0.0.1"
    zone_name: str = "reflex-ddns.com"
    key_name: str = _tsig_defaults.get("TSIG_KEY_NAME", "")
    key_secret: str = _tsig_defaults.get("TSIG_SECRET", "")
    show_secret: bool = False

    # Record fields
    record_name: str = ""
    record_type: str = "A"
    ttl: str = "300"

    # Type-specific fields
    # A / AAAA
    ip_address: str = ""
    # CNAME / NS / PTR
    hostname: str = ""
    # MX
    mx_priority: str = "10"
    mx_server: str = ""
    # TXT
    txt_value: str = ""
    # SRV
    srv_priority: str = "10"
    srv_weight: str = "60"
    srv_port: str = ""
    srv_target: str = ""
    # CAA
    caa_flag: str = "0"
    caa_tag: str = "issue"
    caa_value: str = ""

    # UI state
    is_updating: bool = False
    result_message: str = ""
    result_ok: bool = True

    # History of updates performed this session
    history: list[dict[str, str]] = []

    @rx.event
    def set_record_type(self, value: str):
        self.record_type = value

    @rx.event
    def set_caa_tag(self, value: str):
        self.caa_tag = value

    @rx.event
    def toggle_secret_visibility(self):
        self.show_secret = not self.show_secret

    @rx.event
    def reload_tsig(self):
        fresh = _read_tsig_env_file()
        if not fresh:
            self.result_message = "tsig-secret.env not found (not in Docker?)"
            self.result_ok = False
            return
        if "TSIG_KEY_NAME" in fresh:
            self.key_name = fresh["TSIG_KEY_NAME"]
        if "TSIG_SECRET" in fresh:
            self.key_secret = fresh["TSIG_SECRET"]
        self.result_message = "TSIG credentials reloaded from env file."
        self.result_ok = True

    def _build_rdata(self) -> str:
        """Build the rdata string based on record_type."""
        t = self.record_type
        if t in ("A", "AAAA"):
            return self.ip_address.strip()
        elif t in ("CNAME", "NS", "PTR"):
            h = self.hostname.strip()
            if not h.endswith("."):
                h += "."
            return h
        elif t == "MX":
            s = self.mx_server.strip()
            if not s.endswith("."):
                s += "."
            return f"{self.mx_priority.strip()} {s}"
        elif t == "TXT":
            v = self.txt_value.strip()
            if not v.startswith('"'):
                v = f'"{v}"'
            return v
        elif t == "SRV":
            tgt = self.srv_target.strip()
            if not tgt.endswith("."):
                tgt += "."
            return f"{self.srv_priority.strip()} {self.srv_weight.strip()} {self.srv_port.strip()} {tgt}"
        elif t == "CAA":
            return f'{self.caa_flag.strip()} {self.caa_tag.strip()} "{self.caa_value.strip()}"'
        return ""

    def _validate(self) -> str | None:
        """Return error message or None if valid."""
        if not self.server_ip.strip():
            return "Server IP is required."
        if not self.zone_name.strip():
            return "Zone name is required."
        if not self.record_name.strip():
            return "Record name is required."
        if not self.key_name.strip() or not self.key_secret.strip():
            return "TSIG key name and secret are required."
        try:
            ttl_int = int(self.ttl)
            if ttl_int < 1 or ttl_int > 86400:
                return "TTL must be between 1 and 86400."
        except ValueError:
            return "TTL must be a number."

        t = self.record_type
        if t == "A":
            if not re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", self.ip_address.strip()):
                return "Invalid IPv4 address."
        elif t == "AAAA":
            if not self.ip_address.strip():
                return "IPv6 address is required."
        elif t in ("CNAME", "NS", "PTR"):
            if not self.hostname.strip():
                return "Hostname is required."
        elif t == "MX":
            if not self.mx_server.strip():
                return "Mail server hostname is required."
        elif t == "TXT":
            if not self.txt_value.strip():
                return "TXT value is required."
        elif t == "SRV":
            if not self.srv_port.strip() or not self.srv_target.strip():
                return "SRV port and target are required."
        elif t == "CAA":
            if not self.caa_value.strip():
                return "CAA value is required."
        return None

    @rx.event
    async def execute_update(self):
        """Perform the DNS update via the API."""
        err = self._validate()
        if err:
            self.result_message = err
            self.result_ok = False
            return

        rdata = self._build_rdata()
        self.is_updating = True
        yield

        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as c:
                # Use /api/dns/manual — it persists to manual_dns.json
                # AND updates BIND9, so the record also appears in
                # the DNS Records page.
                resp = await c.post("/api/dns/manual", json={
                    "subdomain": self.record_name.strip(),
                    "zone_name": self.zone_name.strip(),
                    "ip_address": rdata,
                    "record_type": self.record_type,
                    "ttl": int(self.ttl),
                }, timeout=15)
                data = resp.json()
                if data.get("success"):
                    fqdn = f"{self.record_name.strip()}.{self.zone_name.strip()}"
                    self.result_message = f"Updated {self.record_type} {fqdn} → {rdata}"
                    self.result_ok = True
                    self.history.insert(0, {
                        "type": self.record_type,
                        "name": fqdn,
                        "rdata": rdata,
                        "ttl": self.ttl,
                        "status": "success",
                    })
                else:
                    self.result_message = f"Failed: {data.get('message', 'unknown error')}"
                    self.result_ok = False
                    self.history.insert(0, {
                        "type": self.record_type,
                        "name": f"{self.record_name.strip()}.{self.zone_name.strip()}",
                        "rdata": rdata,
                        "ttl": self.ttl,
                        "status": "error",
                    })
        except Exception as exc:
            self.result_message = f"Error: {exc}"
            self.result_ok = False
        self.is_updating = False
