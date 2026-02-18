import reflex as rx
import re
from typing import TypedDict


class ConfigState(rx.State):
    """Manages the configuration for the DDNS client."""

    server_ip: str = ""
    zone_name: str = ""
    record_name: str = "home"
    record_type: str = "A"
    ttl: str = "300"
    key_name: str = ""
    key_secret: str = ""
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
            self.errors["zone_name"] = "Invalid Zone (e.g. example.com)"
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