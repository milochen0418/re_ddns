import reflex as rx
import re
import os
from typing import TypedDict


def _read_tsig_env_file(path: str = "/etc/bind/tsig-secret.env") -> dict[str, str]:
    """Read TSIG key written by entrypoint.sh at container startup.

    Called once at module import time so the values are available as State
    defaults before any browser session connects (e.g. FastAPI endpoints).
    Returns an empty dict silently when running outside Docker.
    """
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


# Evaluated once when Python imports this module – before any HTTP/WS request.
_tsig_defaults = _read_tsig_env_file()


class ConfigState(rx.State):
    """Manages the configuration for the DDNS client."""

    server_ip: str = ""
    zone_name: str = ""
    record_name: str = "home"
    record_type: str = "A"
    ttl: str = "300"
    key_name: str = _tsig_defaults.get("TSIG_KEY_NAME", "")
    key_secret: str = _tsig_defaults.get("TSIG_SECRET", "")
    is_saved: bool = False
    show_secret: bool = False
    errors: dict[str, str] = {}

    @rx.event
    def set_record_type(self, value: str):
        self.record_type = value

    @rx.event
    def toggle_secret_visibility(self):
        self.show_secret = not self.show_secret

    def _validate_ip(self, ip: str) -> bool:
        ipv4_pattern = "^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$"
        hostname_pattern = "^[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
        return bool(re.match(ipv4_pattern, ip)) or bool(re.match(hostname_pattern, ip))

    def _validate_zone(self, zone: str) -> bool:
        return len(zone.split(".")) >= 2

    @rx.event
    def handle_save(self, form_data: dict[str, str]):
        self.errors = {}
        server = form_data.get("server_ip", "").strip()
        zone = form_data.get("zone_name", "").strip()
        record = form_data.get("record_name", "").strip()
        ttl_val = form_data.get("ttl", "").strip()
        k_name = form_data.get("key_name", "").strip()
        k_secret = form_data.get("key_secret", "").strip()
        if not self._validate_ip(server):
            self.errors["server_ip"] = "Invalid IP or Hostname"
        if not self._validate_zone(zone):
            self.errors["zone_name"] = "Invalid Zone (e.g. reflex-ddns.com)"
        if not record:
            self.errors["record_name"] = "Record name required"
        try:
            ttl_int = int(ttl_val)
            if ttl_int < 60 or ttl_int > 86400:
                self.errors["ttl"] = "TTL must be between 60 and 86400"
        except ValueError:
            self.errors["ttl"] = "TTL must be a number"
        if not k_name:
            self.errors["key_name"] = "TSIG Key Name required"
        if not k_secret:
            self.errors["key_secret"] = "TSIG Secret required"
        if not self.errors:
            self.server_ip = server
            self.zone_name = zone
            self.record_name = record
            self.ttl = ttl_val
            self.key_name = k_name
            self.key_secret = k_secret
            self.is_saved = True
            yield rx.toast("Configuration saved successfully!", duration=3000)
        else:
            self.is_saved = False
            yield rx.toast("Please correct the errors in the form.", duration=3000)

    @rx.event
    def edit_config(self):
        self.is_saved = False

    @rx.event
    def reload_tsig_from_env_file(self):
        """Manually reload TSIG credentials from /etc/bind/tsig-secret.env.

        Unlike the module-level initialisation, this always overwrites the
        current values – useful as a UI "Reset to auto-detected key" button.
        """
        fresh = _read_tsig_env_file()
        if not fresh:
            yield rx.toast("tsig-secret.env not found (not running inside Docker?)", duration=4000)
            return
        if "TSIG_KEY_NAME" in fresh:
            self.key_name = fresh["TSIG_KEY_NAME"]
        if "TSIG_SECRET" in fresh:
            self.key_secret = fresh["TSIG_SECRET"]
        yield rx.toast("TSIG credentials reloaded from env file.", duration=3000)