"""State for the DNS Records page.

Provides two lists:
  1. Auto-registered services (from registry.json via API)
  2. Manual DNS records (from manual_dns.json via API)

Also handles adding / deleting manual DNS records from the UI.
"""

import reflex as rx
import httpx
from typing import TypedDict


class ServiceEntry(TypedDict):
    subdomain: str
    zone: str
    upstream_host: str
    frontend_port: int
    backend_port: int
    ip_address: str
    ttl: int


class ManualDNSEntry(TypedDict):
    subdomain: str
    zone: str
    ip_address: str
    record_type: str
    ttl: int


class DNSRecordsState(rx.State):
    """Manages DNS Records page data."""

    services: list[ServiceEntry] = []
    manual_records: list[ManualDNSEntry] = []

    # Form fields for adding manual record
    manual_subdomain: str = ""
    manual_ip: str = ""
    manual_ttl: str = "1"
    manual_record_type: str = "A"

    is_loading: bool = False
    feedback_message: str = ""
    feedback_ok: bool = True

    @rx.event
    async def load_records(self):
        """Fetch both service list and manual DNS from the API."""
        self.is_loading = True
        yield
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as c:
                svc_resp = await c.get("/api/service/list", timeout=5)
                self.services = svc_resp.json() if svc_resp.status_code == 200 else []

                manual_resp = await c.get("/api/dns/manual/list", timeout=5)
                self.manual_records = manual_resp.json() if manual_resp.status_code == 200 else []
        except Exception:
            self.services = []
            self.manual_records = []
        self.is_loading = False

    @rx.event
    async def add_manual_record(self):
        """Add a manual DNS record via the API."""
        sub = self.manual_subdomain.strip()
        ip = self.manual_ip.strip()
        if not sub or not ip:
            self.feedback_message = "Subdomain and IP are required."
            self.feedback_ok = False
            return

        try:
            ttl_val = int(self.manual_ttl)
        except ValueError:
            self.feedback_message = "TTL must be a number."
            self.feedback_ok = False
            return

        self.is_loading = True
        yield
        try:
            # For CNAME/NS/PTR, ensure trailing dot for FQDN
            value = ip
            if self.manual_record_type in ("CNAME", "NS", "PTR"):
                value = value.rstrip("/")
                if not value.endswith("."):
                    value += "."

            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as c:
                resp = await c.post("/api/dns/manual", json={
                    "subdomain": sub,
                    "ip_address": value,
                    "record_type": self.manual_record_type,
                    "ttl": ttl_val,
                }, timeout=10)
                data = resp.json()
                if data.get("success"):
                    self.feedback_message = f"Added {sub}.reflex-ddns.com → {ip}"
                    self.feedback_ok = True
                    self.manual_subdomain = ""
                    self.manual_ip = ""
                    self.manual_ttl = "1"
                    self.manual_record_type = "A"
                else:
                    self.feedback_message = f"Failed: {data.get('message', 'unknown')}"
                    self.feedback_ok = False
        except Exception as exc:
            self.feedback_message = f"Error: {exc}"
            self.feedback_ok = False
        self.is_loading = False
        yield
        yield DNSRecordsState.load_records

    @rx.event
    async def delete_manual_record(self, subdomain: str):
        """Delete a manual DNS record."""
        self.is_loading = True
        yield
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as c:
                resp = await c.delete(f"/api/dns/manual/{subdomain}", timeout=5)
                data = resp.json()
                if data.get("success"):
                    self.feedback_message = f"Deleted {subdomain}"
                    self.feedback_ok = True
                else:
                    self.feedback_message = f"Not found: {subdomain}"
                    self.feedback_ok = False
        except Exception as exc:
            self.feedback_message = f"Error: {exc}"
            self.feedback_ok = False
        self.is_loading = False
        yield
        yield DNSRecordsState.load_records

    @rx.event
    async def delete_service(self, subdomain: str):
        """Unregister an auto-registered service."""
        self.is_loading = True
        yield
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as c:
                resp = await c.delete(f"/api/service/{subdomain}", timeout=10)
                data = resp.json()
                if data.get("success"):
                    self.feedback_message = f"Unregistered {subdomain}"
                    self.feedback_ok = True
                else:
                    self.feedback_message = f"Not found: {subdomain}"
                    self.feedback_ok = False
        except Exception as exc:
            self.feedback_message = f"Error: {exc}"
            self.feedback_ok = False
        self.is_loading = False
        yield
        yield DNSRecordsState.load_records
