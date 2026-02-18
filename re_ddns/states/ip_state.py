import reflex as rx
import httpx
import asyncio
from datetime import datetime
import logging


class IPState(rx.State):
    """Manages external IP detection and monitoring status."""

    current_ip: str = "--.--.--.--"
    previous_ip: str = ""
    last_checked: str = "Never"
    is_loading: bool = False
    ip_changed: bool = False
    check_interval: int = 60
    is_monitoring: bool = False

    @rx.event(background=True)
    async def check_ip_periodically(self):
        """Background task that runs the IP check loop."""
        while True:
            async with self:
                if not self.is_monitoring:
                    break
                interval = self.check_interval
            yield IPState.detect_ip
            await asyncio.sleep(interval)

    @rx.event
    def toggle_monitoring(self):
        """Toggles the automatic monitoring on/off."""
        self.is_monitoring = not self.is_monitoring
        if self.is_monitoring:
            return IPState.check_ip_periodically

    @rx.event(background=True)
    async def detect_ip(self):
        """Fetches the current external IP address."""
        async with self:
            self.is_loading = True
        ip_url = "https://api64.ipify.org?format=json"
        new_ip = None
        error = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(ip_url, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                new_ip = data.get("ip")
        except Exception as e:
            logging.exception("Unexpected error")
            error = str(e)
            logging.error(f"IP Detection failed: {e}")
        async with self:
            if new_ip:
                if self.current_ip != "--.--.--.--" and self.current_ip != new_ip:
                    self.previous_ip = self.current_ip
                    self.ip_changed = True
                else:
                    self.ip_changed = False
                self.current_ip = new_ip
                self.last_checked = datetime.now().strftime("%H:%M:%S")
            if self.ip_changed and self.is_monitoring:
                from re_ddns.states.dns_update_state import DNSUpdateState

                yield DNSUpdateState.update_dns
            self.is_loading = False
            if error:
                yield rx.toast(f"Failed to check IP: {error}")