import reflex as rx
import dns.update
import dns.query
import dns.tsigkeyring
import dns.rdatatype
import logging
import time
from re_ddns.states.config import ConfigState
from re_ddns.states.ip_state import IPState
from re_ddns.states.activity_log_state import ActivityLogState


class DNSUpdateState(rx.State):
    """Manages RFC 2136 DNS updates."""

    is_updating: bool = False
    last_update_status: str = ""
    last_update_message: str = ""

    @rx.event(background=True)
    async def update_dns(self):
        """Performs the DNS update using current configuration and detected IP."""
        async with self:
            if self.is_updating:
                return
            self.is_updating = True
            self.last_update_status = ""
            self.last_update_message = ""
            config = await self.get_state(ConfigState)
            ip_state = await self.get_state(IPState)
            log_state = await self.get_state(ActivityLogState)
            if not config.is_saved:
                self.is_updating = False
                self.last_update_status = "error"
                msg = "Configuration not saved. Please configure settings first."
                self.last_update_message = msg
                log_state.add_log("error", msg, "--")
                yield rx.toast(msg)
                return
            current_ip = ip_state.current_ip
            if not current_ip or current_ip == "--.--.--.--":
                self.is_updating = False
                self.last_update_status = "error"
                msg = "No valid IP address detected yet."
                self.last_update_message = msg
                log_state.add_log("error", msg, "--")
                yield rx.toast(msg)
                return
            server = config.server_ip
            zone = config.zone_name
            record = config.record_name
            rtype = config.record_type
            ttl = int(config.ttl)
            key_name = config.key_name
            key_secret = config.key_secret
        try:
            keyring = dns.tsigkeyring.from_text({key_name: key_secret})
            update = dns.update.Update(zone, keyring=keyring)
            update.replace(record, ttl, rtype, current_ip)
            response = dns.query.tcp(update, server, timeout=10.0)
            rcode = response.rcode()
            if rcode != dns.rcode.NOERROR:
                raise Exception(
                    f"DNS Update failed with RCODE: {dns.rcode.to_text(rcode)}"
                )
            success_msg = f"Successfully updated {record}.{zone} to {current_ip}"
            async with self:
                self.last_update_status = "success"
                self.last_update_message = success_msg
                log_state.add_log("success", success_msg, current_ip)
                yield rx.toast(success_msg)
        except Exception as e:
            logging.exception("Unexpected error")
            error_msg = f"Update failed: {str(e)}"
            logging.error(error_msg)
            async with self:
                self.last_update_status = "error"
                self.last_update_message = error_msg
                log_state.add_log("error", error_msg, current_ip)
                yield rx.toast(error_msg)
        finally:
            async with self:
                self.is_updating = False