"""FastAPI router – DNS + service-registration endpoints.

All mutations flow through the JSON **registry** which is the single
source of truth:

1. ``POST /api/service/register`` → ``registry.put_service()``
   → ``nginx_manager.sync()`` → ``_do_dns_update()``
2. ``DELETE /api/service/{subdomain}`` → ``registry.delete_service()``
   → ``nginx_manager.sync()``
3. ``GET /api/service/list`` / ``GET /api/dns/status`` are read-only.
4. ``POST /api/dns/update`` is a low-level escape hatch that does NOT
   touch the registry (direct RFC 2136 update).
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
from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from re_ddns.api import cert_manager, nginx_manager, registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dns", "service"])


# ---------------------------------------------------------------------------
# Helpers – read server-side TSIG defaults
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
# Request / Response models
# ---------------------------------------------------------------------------

class DNSUpdateRequest(BaseModel):
    """Body for ``POST /api/dns/update`` (low-level)."""
    server_ip: str = "127.0.0.1"
    zone_name: str = "reflex-ddns.com"
    record_name: str
    record_type: str = "A"
    ttl: int = 60
    ip_address: str
    key_name: Optional[str] = None
    key_secret: Optional[str] = None


class DNSUpdateResponse(BaseModel):
    success: bool
    message: str


class DNSStatusResponse(BaseModel):
    status: str
    service: str


class ServiceRegisterRequest(BaseModel):
    """Body for ``POST /api/service/register``."""
    subdomain: str
    zone_name: str = "reflex-ddns.com"
    upstream_host: str
    frontend_port: int = 3000
    backend_port: int = 8000
    ip_address: str = "127.0.0.1"
    ttl: int = 60


class ServiceRegisterResponse(BaseModel):
    success: bool
    dns_ok: bool
    nginx_ok: bool
    tls_ok: bool
    message: str


class ServiceListItem(BaseModel):
    subdomain: str
    zone: str
    upstream_host: str
    frontend_port: int
    backend_port: int
    ip_address: str
    ttl: int


# ---------------------------------------------------------------------------
# Internal DNS helper
# ---------------------------------------------------------------------------

def _do_dns_update(
    record_name: str,
    zone_name: str,
    ip_address: str,
    ttl: int,
) -> tuple[bool, str]:
    """Perform an RFC 2136 DNS update using server-side TSIG defaults."""
    key_name = _tsig.get("TSIG_KEY_NAME", "")
    key_secret = _tsig.get("TSIG_SECRET", "")
    if not key_name or not key_secret:
        return False, "No server-side TSIG credentials available."

    try:
        keyring = dns.tsigkeyring.from_text({key_name: key_secret})
        update = dns.update.Update(zone_name, keyring=keyring)
        update.replace(record_name, ttl, "A", ip_address)
        response = dns.query.tcp(update, "127.0.0.1", timeout=10.0)
        rcode_val = response.rcode()
        if rcode_val != dns.rcode.NOERROR:
            return False, f"DNS RCODE: {dns.rcode.to_text(rcode_val)}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dns/status", response_model=DNSStatusResponse)
async def dns_status():
    """Health-check endpoint."""
    return DNSStatusResponse(status="ok", service="re-ddns")


@router.post("/dns/update", response_model=DNSUpdateResponse)
async def update_dns_record(req: DNSUpdateRequest):
    """Low-level: create / replace a DNS record (does NOT touch registry)."""
    key_name = req.key_name or _tsig.get("TSIG_KEY_NAME", "")
    key_secret = req.key_secret or _tsig.get("TSIG_SECRET", "")

    if not key_name or not key_secret:
        return DNSUpdateResponse(
            success=False,
            message="TSIG credentials required but unavailable.",
        )

    fqdn = f"{req.record_name}.{req.zone_name}"
    logger.info("dns/update: %s %s -> %s", req.record_type, fqdn, req.ip_address)

    try:
        keyring = dns.tsigkeyring.from_text({key_name: key_secret})
        update = dns.update.Update(req.zone_name, keyring=keyring)
        update.replace(req.record_name, req.ttl, req.record_type, req.ip_address)
        response = dns.query.tcp(update, req.server_ip, timeout=10.0)
        rcode_val = response.rcode()
        if rcode_val != dns.rcode.NOERROR:
            msg = f"DNS update failed: {dns.rcode.to_text(rcode_val)}"
            logger.error(msg)
            return DNSUpdateResponse(success=False, message=msg)

        msg = f"Updated {fqdn} ({req.record_type}) -> {req.ip_address} (TTL {req.ttl})"
        logger.info(msg)
        return DNSUpdateResponse(success=True, message=msg)

    except Exception as exc:
        logger.exception("DNS update error")
        return DNSUpdateResponse(success=False, message=str(exc))


# ---------------------------------------------------------------------------
# Service registration – single call configures registry + DNS + nginx
# ---------------------------------------------------------------------------

@router.post("/service/register", response_model=ServiceRegisterResponse)
async def register_service_endpoint(req: ServiceRegisterRequest):
    """Register a service: registry → DNS → TLS cert → nginx (with HTTPS)."""

    fqdn = f"{req.subdomain}.{req.zone_name}"
    logger.info(
        "service/register: %s -> upstream=%s:%d, dns=%s",
        fqdn, req.upstream_host, req.frontend_port, req.ip_address,
    )

    # 1) Registry (source of truth)
    registry.put_service(
        subdomain=req.subdomain,
        zone=req.zone_name,
        upstream_host=req.upstream_host,
        frontend_port=req.frontend_port,
        backend_port=req.backend_port,
        ip_address=req.ip_address,
        ttl=req.ttl,
    )

    # 2) DNS A record
    dns_ok, dns_msg = _do_dns_update(
        req.subdomain, req.zone_name, req.ip_address, req.ttl,
    )
    if not dns_ok:
        logger.warning("DNS failed for %s: %s", fqdn, dns_msg)

    # 3) TLS certificate
    #    For self-signed: generated immediately.
    #    For letsencrypt: needs DNS + HTTP serving first, so we sync
    #    nginx once with HTTP-only, then obtain the cert, then re-sync.
    tls_ok = False
    if cert_manager.TLS_MODE == "letsencrypt":
        # First sync: HTTP + ACME challenge location (no cert yet)
        nginx_manager.sync()
        tls_ok = cert_manager.ensure_cert(fqdn)
    else:
        # self-signed or none
        tls_ok = cert_manager.ensure_cert(fqdn)

    # 4) Sync nginx from registry (now with HTTPS if cert exists)
    nginx_ok = True
    try:
        nginx_ok = nginx_manager.sync()
    except Exception as exc:
        logger.exception("nginx sync failed for %s", fqdn)
        nginx_ok = False

    success = dns_ok and nginx_ok
    parts = []
    if dns_ok:
        parts.append(f"DNS: {fqdn} -> {req.ip_address}")
    else:
        parts.append(f"DNS failed: {dns_msg}")
    if nginx_ok:
        parts.append(f"nginx: {fqdn} -> {req.upstream_host}:{req.frontend_port}")
    else:
        parts.append("nginx sync failed")
    if tls_ok:
        parts.append(f"TLS: {cert_manager.TLS_MODE}")
    else:
        parts.append(f"TLS: skipped ({cert_manager.TLS_MODE})")

    return ServiceRegisterResponse(
        success=success,
        dns_ok=dns_ok,
        nginx_ok=nginx_ok,
        tls_ok=tls_ok,
        message=" | ".join(parts),
    )


@router.delete("/service/{subdomain}")
async def unregister_service_endpoint(subdomain: str):
    """Remove a service from registry + nginx (DNS TTL will expire)."""
    existed = registry.delete_service(subdomain)
    nginx_ok = True
    if existed:
        try:
            nginx_ok = nginx_manager.sync()
        except Exception:
            nginx_ok = False
    return {"success": existed, "nginx_synced": nginx_ok, "subdomain": subdomain}


@router.get("/service/list", response_model=list[ServiceListItem])
async def list_services_endpoint():
    """List all registered services (from registry)."""
    return registry.list_services()


# ---------------------------------------------------------------------------
# CA certificate — verify, download & install helpers
# ---------------------------------------------------------------------------

@router.get("/ca/verify")
async def ca_verify():
    """Return CA status, TLS mode, and fingerprint.

    Responds with ``Access-Control-Allow-Origin: *`` so that a page
    served over HTTP can probe the HTTPS version of this endpoint to
    decide whether the browser trusts the CA certificate.
    """
    has_ca = cert_manager.has_ca()
    return JSONResponse(
        content={
            "tls_mode": cert_manager.TLS_MODE,
            "has_ca": has_ca,
            "fingerprint": cert_manager.ca_fingerprint() if has_ca else "",
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
        },
    )


@router.get("/ca.pem")
async def download_ca_cert():
    """Download the Local CA root certificate (PEM format).

    Users import this into their OS / browser trust store so that all
    ``*.reflex-ddns.com`` HTTPS sites are trusted automatically.
    """
    pem = cert_manager.ca_pem_bytes()
    if not pem:
        return PlainTextResponse(
            "No CA certificate available (TLS_MODE may be 'none').",
            status_code=404,
        )
    return Response(
        content=pem,
        media_type="application/x-pem-file",
        headers={
            "Content-Disposition": "attachment; filename=re_ddns_ca.pem",
        },
    )


@router.get("/ca/install-script/{platform}")
async def ca_install_script(platform: str):
    """Return a ready-to-run install script for the CA certificate.

    Supported platforms: ``macos``, ``linux``, ``windows``.
    """
    # The API URL visible to the client (they access via nginx on :80)
    base = "http://home.reflex-ddns.com"
    download = f"{base}/api/ca.pem"

    scripts = {
        "macos": (
            "#!/bin/bash\n"
            "# Re-DDNS Local CA — macOS installer\n"
            "set -e\n"
            f'echo "Downloading CA certificate from {download} ..."\n'
            f'curl -sSfL -o /tmp/re_ddns_ca.pem "{download}"\n'
            'echo "Installing into System Keychain (requires admin password) ..."\n'
            "sudo security add-trusted-cert -d -r trustRoot "
            "-k /Library/Keychains/System.keychain /tmp/re_ddns_ca.pem\n"
            'echo ""\n'
            'echo "Done! All *.reflex-ddns.com HTTPS sites are now trusted."\n'
            'echo "You may need to restart your browser."\n'
        ),
        "linux": (
            "#!/bin/bash\n"
            "# Re-DDNS Local CA — Linux installer (Debian/Ubuntu)\n"
            "set -e\n"
            f'echo "Downloading CA certificate from {download} ..."\n'
            f'curl -sSfL -o /tmp/re_ddns_ca.pem "{download}"\n'
            'echo "Installing system-wide (requires root) ..."\n'
            "sudo cp /tmp/re_ddns_ca.pem /usr/local/share/ca-certificates/re_ddns_ca.crt\n"
            "sudo update-ca-certificates\n"
            'echo ""\n'
            'echo "Done! System tools (curl, wget) now trust *.reflex-ddns.com."\n'
            'echo ""\n'
            'echo "For browsers:"\n'
            'echo "  Chrome: Settings → Privacy → Manage certificates → Authorities → Import"\n'
            'echo "  Firefox: Settings → Privacy → View Certificates → Authorities → Import"\n'
            'echo "  Import the file: /tmp/re_ddns_ca.pem"\n'
        ),
        "windows": (
            "# Re-DDNS Local CA — Windows installer (PowerShell, run as Admin)\n"
            f'$url = "{download}"\n'
            '$outFile = "$env:TEMP\\re_ddns_ca.pem"\n'
            '\n'
            'Write-Host "Downloading CA certificate ..."\n'
            "Invoke-WebRequest -Uri $url -OutFile $outFile\n"
            '\n'
            'Write-Host "Installing to Trusted Root Certification Authorities ..."\n'
            "Import-Certificate -FilePath $outFile "
            "-CertStoreLocation Cert:\\LocalMachine\\Root\n"
            '\n'
            'Write-Host ""\n'
            'Write-Host "Done! All *.reflex-ddns.com HTTPS sites are now trusted."\n'
            'Write-Host "You may need to restart your browser."\n'
        ),
    }

    content = scripts.get(platform.lower())
    if content is None:
        return PlainTextResponse(
            f"Unknown platform '{platform}'. Use: macos, linux, windows",
            status_code=400,
        )

    ext = ".ps1" if platform.lower() == "windows" else ".sh"
    return PlainTextResponse(
        content=content,
        headers={
            "Content-Disposition": f"attachment; filename=install_ca{ext}",
        },
    )
