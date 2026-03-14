"""Service registry + FastAPI router.

This module is the **single entry-point** for service management:

1. It owns the JSON registry (``/app/data/registry.json``) — the
   single source of truth for all registered services.
2. It exposes FastAPI endpoints that first persist changes to the
   registry, then delegate to the infrastructure managers:
   - ``dns_manager``   — RFC 2136 dynamic DNS updates
   - ``cert_manager``  — TLS certificate provisioning
   - ``nginx_manager`` — reverse-proxy configuration

Flow for ``POST /api/service/register``::

    registry_api  ──►  write JSON (registry)
         │
         ├──►  dns_manager.do_dns_update()
         ├──►  cert_manager.ensure_cert()
         └──►  nginx_manager.sync()   (reads the JSON it needs itself)

File layout (default ``/app/data/registry.json``)::

    {
      "services": {
        "testapp": {
          "subdomain": "testapp",
          "zone": "reflex-ddns.com",
          "upstream_host": "test-app",
          "frontend_port": 3000,
          "backend_port": 8000,
          "ip_address": "127.0.0.1",
          "ttl": 60,
          "registered_at": "2026-03-05T12:00:00"
        }
      }
    }

Thread-safe: all reads/writes are protected by a ``threading.Lock``.
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from re_ddns.api import cert_manager, dns_manager, nginx_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dns", "service"])

# ---------------------------------------------------------------------------
# Registry data layer
# ---------------------------------------------------------------------------

_DEFAULT_PATH = Path("/app/data/registry.json")
_lock = Lock()

# Module-level path — can be overridden via ``init()``.
_registry_path: Path = _DEFAULT_PATH


def _own_ip() -> str:
    """Return this container's network IP (for DNS A records).

    All registered services should have DNS pointing to re-ddns (the
    nginx proxy), NOT to their own container IPs."""
    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        return "127.0.0.1"


def _empty_registry() -> dict[str, Any]:
    return {"services": {}}


def _ensure_file(path: Path) -> None:
    """Create the registry file (+ parent dirs) if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(_empty_registry(), indent=2) + "\n")
        logger.info("Created new registry file: %s", path)


def init(path: Path | str | None = None) -> Path:
    """Initialise the registry.  Call once at startup.

    Returns the resolved path for logging purposes.
    """
    global _registry_path
    if path is not None:
        _registry_path = Path(path)
    _ensure_file(_registry_path)
    logger.info("Registry initialised: %s", _registry_path)
    return _registry_path


def load() -> dict[str, Any]:
    """Return the full registry dict (deep copy)."""
    with _lock:
        _ensure_file(_registry_path)
        return json.loads(_registry_path.read_text())


def save(data: dict[str, Any]) -> None:
    """Overwrite the registry file atomically."""
    with _lock:
        _ensure_file(_registry_path)
        tmp = _registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(_registry_path)


def get_service(subdomain: str) -> dict[str, Any] | None:
    """Return a single service entry, or *None*."""
    data = load()
    return data["services"].get(subdomain)


def put_service(
    subdomain: str,
    zone: str,
    upstream_host: str,
    frontend_port: int = 3000,
    backend_port: int = 8000,
    ip_address: str = "127.0.0.1",
    ttl: int = 60,
) -> dict[str, Any]:
    """Insert or update a service.  Returns the entry written."""
    entry = {
        "subdomain": subdomain,
        "zone": zone,
        "upstream_host": upstream_host,
        "frontend_port": frontend_port,
        "backend_port": backend_port,
        "ip_address": ip_address,
        "ttl": ttl,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    data = load()
    data["services"][subdomain] = entry
    save(data)
    logger.info("Registry: put service '%s'", subdomain)
    return entry


def delete_service(subdomain: str) -> bool:
    """Remove a service.  Returns *True* if it existed."""
    data = load()
    if subdomain not in data["services"]:
        return False
    del data["services"][subdomain]
    save(data)
    logger.info("Registry: deleted service '%s'", subdomain)
    return True


def list_services() -> list[dict[str, Any]]:
    """Return a list of all service entries."""
    data = load()
    return list(data["services"].values())


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
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dns/status", response_model=DNSStatusResponse)
async def dns_status():
    """Health-check endpoint."""
    return DNSStatusResponse(status="ok", service="re-ddns")


@router.post("/dns/update", response_model=DNSUpdateResponse)
async def update_dns_record(req: DNSUpdateRequest):
    """Low-level: create / replace a DNS record (does NOT touch registry)."""
    fqdn = f"{req.record_name}.{req.zone_name}"
    logger.info("dns/update: %s %s -> %s", req.record_type, fqdn, req.ip_address)

    ok, msg = dns_manager.do_dns_update(
        record_name=req.record_name,
        zone_name=req.zone_name,
        ip_address=req.ip_address,
        ttl=req.ttl,
        record_type=req.record_type,
        key_name=req.key_name or None,
        key_secret=req.key_secret or None,
        server_ip=req.server_ip,
    )

    if ok:
        msg = f"Updated {fqdn} ({req.record_type}) -> {req.ip_address} (TTL {req.ttl})"
        logger.info(msg)
    else:
        logger.error("DNS update failed: %s", msg)

    return DNSUpdateResponse(success=ok, message=msg)


# ---------------------------------------------------------------------------
# Service registration – single call configures registry + DNS + nginx
# ---------------------------------------------------------------------------

@router.post("/service/register", response_model=ServiceRegisterResponse)
async def register_service_endpoint(req: ServiceRegisterRequest):
    """Register a service: registry → DNS → TLS cert → nginx (with HTTPS)."""

    fqdn = f"{req.subdomain}.{req.zone_name}"
    # DNS A records must point to re-ddns (the nginx proxy), not to the
    # service container's own IP — HTTPS terminates here.
    proxy_ip = _own_ip()
    logger.info(
        "service/register: %s -> upstream=%s:%d, dns=%s (client sent %s)",
        fqdn, req.upstream_host, req.frontend_port, proxy_ip, req.ip_address,
    )

    # 1) Registry (source of truth) — write JSON first
    put_service(
        subdomain=req.subdomain,
        zone=req.zone_name,
        upstream_host=req.upstream_host,
        frontend_port=req.frontend_port,
        backend_port=req.backend_port,
        ip_address=proxy_ip,
        ttl=req.ttl,
    )

    # 2) DNS A record — point to re-ddns (nginx proxy)
    dns_ok, dns_msg = dns_manager.do_dns_update(
        req.subdomain, req.zone_name, proxy_ip, req.ttl,
    )
    if not dns_ok:
        logger.warning("DNS failed for %s: %s", fqdn, dns_msg)

    # 3) TLS certificate
    #    For letsencrypt: needs DNS + HTTP serving first, so we sync
    #    nginx once with HTTP-only, then obtain the cert, then re-sync.
    tls_ok = False
    if cert_manager.TLS_MODE == "letsencrypt":
        # First sync: HTTP + ACME challenge location (no cert yet)
        nginx_manager.sync()
        tls_ok = cert_manager.ensure_cert(fqdn)
    else:
        # local-ca or none
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
        parts.append(f"DNS: {fqdn} -> {proxy_ip}")
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
    existed = delete_service(subdomain)
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
    return list_services()


# ---------------------------------------------------------------------------
# CA certificate — verify, download & install helpers
# ---------------------------------------------------------------------------

@router.get("/origin")
async def get_origin(request: Request):
    """Return the origin/base-URL as seen by the client.

    The Reflex app runs on localhost:3000/8000, but nginx proxies
    requests and forwards the original ``Host`` header.  This endpoint
    lets any client (browser JS or CLI) discover the externally-visible
    domain name without hardcoding it.

    Example response::

        {
            "host": "home.reflex-ddns.com",
            "scheme": "https",
            "base_url": "https://home.reflex-ddns.com"
        }
    """
    host = request.headers.get("host", request.base_url.hostname or "localhost")
    # Strip port if it's a default port
    if ":" in host:
        h, p = host.rsplit(":", 1)
        if p in ("80", "443"):
            host = h
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return JSONResponse(
        content={"host": host, "scheme": scheme, "base_url": f"{scheme}://{host}"},
        headers={"Access-Control-Allow-Origin": "*"},
    )


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
async def ca_install_script(platform: str, request: Request):
    """Return a ready-to-run install script for the CA certificate.

    Supported platforms: ``macos``, ``linux``, ``windows``.

    The download URL is derived from the incoming ``Host`` header so the
    script works regardless of which domain/IP the user accessed.
    """
    # Derive the base URL from the request Host header (set by nginx)
    host = request.headers.get("host", request.base_url.hostname or "localhost")
    if ":" in host:
        h, p = host.rsplit(":", 1)
        if p in ("80", "443"):
            host = h
    # Install scripts run from a terminal (no browser TLS), so use HTTP
    base = f"http://{host}"
    download = f"{base}/api/ca.pem"

    scripts = {
        "macos": (
            "#!/bin/bash\n"
            "# Re-DDNS Local CA — macOS smart installer (AppleScript GUI)\n"
            "# Uses native macOS dialogs for a friendly user experience.\n"
            "\n"
            'CA_NAME="Re-DDNS Root CA"\n'
            'KEYCHAIN="/Library/Keychains/System.keychain"\n'
            'TMP_PEM="/tmp/re_ddns_ca.pem"\n'
            f'DOWNLOAD_URL="{download}"\n'
            f'HOST="{host}"\n'
            "\n"
            "# ── Detect current CA status ──\n"
            'INSTALLED=0\n'
            'TRUSTED=0\n'
            'STATUS_ICON="❌"\n'
            'STATUS_TEXT="Not installed"\n'
            "\n"
            'if security find-certificate -c "$CA_NAME" "$KEYCHAIN" >/dev/null 2>&1; then\n'
            '    INSTALLED=1\n'
            '    TRUST_INFO=$(security dump-trust-settings -d 2>/dev/null || true)\n'
            '    if echo "$TRUST_INFO" | grep -q "$CA_NAME"; then\n'
            '        TRUSTED=1\n'
            '        STATUS_ICON="✅"\n'
            '        STATUS_TEXT="Installed and trusted (System Keychain)"\n'
            '    else\n'
            '        STATUS_ICON="⚠️"\n'
            '        STATUS_TEXT="Installed but NOT fully trusted"\n'
            '    fi\n'
            'fi\n'
            "\n"
            "# ── Show status + menu via AppleScript ──\n"
            'if [ "$INSTALLED" -eq 1 ]; then\n'
            '    CHOICE=$(osascript <<EOF\n'
            "tell application \"System Events\"\n"
            "    set dialogResult to display dialog \\\n"
            '        "$STATUS_ICON  Re-DDNS Root CA" & return & return & \\\n'
            '        "Status:  $STATUS_TEXT" & return & return & \\\n'
            '        "What would you like to do?" \\\n'
            "        with title \"Re-DDNS CA Certificate Tool\" \\\n"
            '        buttons {"Cancel", "Remove", "Reinstall"} \\\n'
            '        default button "Reinstall" \\\n'
            "        with icon caution\n"
            "    return button returned of dialogResult\n"
            "end tell\n"
            "EOF\n"
            '    ) || { echo "Cancelled."; exit 0; }\n'
            'else\n'
            '    CHOICE=$(osascript <<EOF\n'
            "tell application \"System Events\"\n"
            "    set dialogResult to display dialog \\\n"
            '        "$STATUS_ICON  Re-DDNS Root CA" & return & return & \\\n'
            '        "Status:  $STATUS_TEXT" & return & return & \\\n'
            '        "Install the CA certificate to trust all" & return & \\\n'
            '        "*.reflex-ddns.com HTTPS sites?" \\\n'
            "        with title \"Re-DDNS CA Certificate Tool\" \\\n"
            '        buttons {"Cancel", "Install"} \\\n'
            '        default button "Install" \\\n'
            "        with icon note\n"
            "    return button returned of dialogResult\n"
            "end tell\n"
            "EOF\n"
            '    ) || { echo "Cancelled."; exit 0; }\n'
            'fi\n'
            "\n"
            "# ── Helper functions ──\n"
            "do_download() {\n"
            '    curl -fL -o "$TMP_PEM" "$DOWNLOAD_URL"\n'
            "}\n"
            "\n"
            "do_install() {\n"
            "    # sudo properly acquires the authorization context needed\n"
            "    # by SecTrustSettingsSetTrustSettings (osascript cannot).\n"
            '    sudo security add-trusted-cert -d -r trustRoot -k "$KEYCHAIN" "$TMP_PEM"\n'
            "}\n"
            "\n"
            "do_remove() {\n"
            '    CERT_SHA1=$(security find-certificate -c "$CA_NAME" -Z "$KEYCHAIN" 2>/dev/null \\\n'
            "        | awk '/SHA-1 hash:/{print $NF}')\n"
            '    if [ -n "$CERT_SHA1" ]; then\n'
            '        sudo security delete-certificate -Z "$CERT_SHA1" "$KEYCHAIN"\n'
            '    fi\n'
            "}\n"
            "\n"
            "notify_ok() {\n"
            '    osascript -e "display dialog \\"$1\\" with title \\"Re-DDNS CA\\" buttons {\\"OK\\"} default button \\"OK\\" with icon note"\n'
            "}\n"
            "\n"
            "notify_err() {\n"
            '    osascript -e "display dialog \\"$1\\" with title \\"Re-DDNS CA\\" buttons {\\"OK\\"} default button \\"OK\\" with icon stop"\n'
            "}\n"
            "\n"
            "# ── Execute chosen action ──\n"
            'case "$CHOICE" in\n'
            '    "Install")\n'
            "        do_download && do_install \\\n"
            f'            && notify_ok "✅ CA certificate installed!\\n\\nAll HTTPS sites under {host} are now trusted.\\nPlease restart your browser." \\\n'
            '            || notify_err "❌ Installation failed.\\nPlease try again."\n'
            "        ;;\n"
            '    "Reinstall")\n'
            "        do_remove 2>/dev/null || true\n"
            "        do_download && do_install \\\n"
            f'            && notify_ok "✅ CA certificate reinstalled!\\n\\nThe latest certificate for {host} is now active.\\nPlease restart your browser." \\\n'
            '            || notify_err "❌ Reinstallation failed.\\nPlease try again."\n'
            "        ;;\n"
            '    "Remove")\n'
            "        do_remove \\\n"
            '            && notify_ok "✅ CA certificate removed.\\n\\nHTTPS sites under *.reflex-ddns.com will no longer be trusted.\\nPlease restart your browser." \\\n'
            '            || notify_err "❌ Removal failed.\\nThe certificate may have been removed already."\n'
            "        ;;\n"
            "    *)\n"
            '        echo "Cancelled."\n'
            "        ;;\n"
            "esac\n"
        ),
        "linux": (
            "#!/bin/bash\n"
            "# Re-DDNS Local CA — Linux smart installer (Zenity GUI)\n"
            "# Uses zenity dialogs for a friendly user experience.\n"
            "# Falls back to terminal-only mode if no display is available.\n"
            "\n"
            f'CA_NAME="Re-DDNS CA"\n'
            f'TMP_PEM="/tmp/re_ddns_ca.pem"\n'
            f'DOWNLOAD_URL="{download}"\n'
            f'HOST="{host}"\n'
            'SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"\n'
            'NSS_DB="$HOME/.pki/nssdb"\n'
            'CA_CERT="/usr/local/share/ca-certificates/re_ddns_ca.crt"\n'
            "\n"
            "# ── Ensure zenity is available ──\n"
            'HAS_GUI=0\n'
            'if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then\n'
            '    if ! command -v zenity >/dev/null 2>&1; then\n'
            '        echo "Installing zenity for GUI dialogs ..."\n'
            '        $SUDO apt-get update -qq && $SUDO apt-get install -y -qq zenity >/dev/null 2>&1 || true\n'
            '    fi\n'
            '    command -v zenity >/dev/null 2>&1 && HAS_GUI=1\n'
            'fi\n'
            "\n"
            "# ── Ensure certutil is available ──\n"
            'if ! command -v certutil >/dev/null 2>&1; then\n'
            '    echo "Installing libnss3-tools (certutil) for Chromium ..."\n'
            '    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq libnss3-tools >/dev/null 2>&1 || true\n'
            'fi\n'
            "\n"
            "# ── GUI helper functions ──\n"
            "gui_info() {\n"
            '    if [ "$HAS_GUI" -eq 1 ]; then\n'
            '        zenity --info --title="Re-DDNS CA" --text="$1" --width=400 2>/dev/null\n'
            '    else\n'
            '        echo "$1"\n'
            '    fi\n'
            "}\n"
            "\n"
            "gui_error() {\n"
            '    if [ "$HAS_GUI" -eq 1 ]; then\n'
            '        zenity --error --title="Re-DDNS CA" --text="$1" --width=400 2>/dev/null\n'
            '    else\n'
            '        echo "ERROR: $1" >&2\n'
            '    fi\n'
            "}\n"
            "\n"
            "gui_question() {\n"
            "    # $1=text  returns 0=Yes/1=No\n"
            '    if [ "$HAS_GUI" -eq 1 ]; then\n'
            '        zenity --question --title="Re-DDNS CA" --text="$1" --width=400 2>/dev/null\n'
            '    else\n'
            '        read -rp "$1 [y/N] " ans; [ "$ans" = "y" ] || [ "$ans" = "Y" ]\n'
            '    fi\n'
            "}\n"
            "\n"
            "# ── Detect current CA status ──\n"
            'INSTALLED_SYSTEM=0\n'
            'INSTALLED_CHROMIUM=0\n'
            'STATUS_ICON="❌"\n'
            'STATUS_TEXT="Not installed"\n'
            "\n"
            '# Check system CA store\n'
            'if [ -f "$CA_CERT" ]; then\n'
            '    INSTALLED_SYSTEM=1\n'
            'fi\n'
            "\n"
            '# Check Chromium NSS database\n'
            'if command -v certutil >/dev/null 2>&1 && [ -d "$NSS_DB" ]; then\n'
            '    certutil -d sql:"$NSS_DB" -L -n "$CA_NAME" >/dev/null 2>&1 && INSTALLED_CHROMIUM=1\n'
            'fi\n'
            "\n"
            '# Build status string\n'
            'if [ "$INSTALLED_SYSTEM" -eq 1 ] && [ "$INSTALLED_CHROMIUM" -eq 1 ]; then\n'
            '    STATUS_ICON="✅"\n'
            '    STATUS_TEXT="Installed (system + Chromium)"\n'
            'elif [ "$INSTALLED_SYSTEM" -eq 1 ]; then\n'
            '    STATUS_ICON="⚠️"\n'
            '    STATUS_TEXT="Installed (system only, not in Chromium)"\n'
            'elif [ "$INSTALLED_CHROMIUM" -eq 1 ]; then\n'
            '    STATUS_ICON="⚠️"\n'
            '    STATUS_TEXT="Installed (Chromium only, not system-wide)"\n'
            'fi\n'
            "\n"
            "# ── Action functions ──\n"
            "do_download() {\n"
            '    curl -sSfL -o "$TMP_PEM" "$DOWNLOAD_URL"\n'
            "}\n"
            "\n"
            "do_install_system() {\n"
            '    $SUDO cp "$TMP_PEM" "$CA_CERT"\n'
            '    $SUDO update-ca-certificates\n'
            "}\n"
            "\n"
            "do_install_chromium() {\n"
            '    if command -v certutil >/dev/null 2>&1; then\n'
            '        mkdir -p "$NSS_DB"\n'
            '        [ ! -f "$NSS_DB/cert9.db" ] && certutil -d sql:"$NSS_DB" -N --empty-password 2>/dev/null || true\n'
            '        certutil -d sql:"$NSS_DB" -D -n "$CA_NAME" 2>/dev/null || true\n'
            '        certutil -d sql:"$NSS_DB" -A -t "C,," -n "$CA_NAME" -i "$TMP_PEM"\n'
            '    fi\n'
            "}\n"
            "\n"
            "do_install() {\n"
            "    do_download && do_install_system && do_install_chromium\n"
            "}\n"
            "\n"
            "do_remove_system() {\n"
            '    [ -f "$CA_CERT" ] && $SUDO rm -f "$CA_CERT" && $SUDO update-ca-certificates --fresh\n'
            "}\n"
            "\n"
            "do_remove_chromium() {\n"
            '    if command -v certutil >/dev/null 2>&1 && [ -d "$NSS_DB" ]; then\n'
            '        certutil -d sql:"$NSS_DB" -D -n "$CA_NAME" 2>/dev/null || true\n'
            '    fi\n'
            "}\n"
            "\n"
            "do_remove() {\n"
            "    do_remove_system; do_remove_chromium\n"
            "}\n"
            "\n"
            "# ── Show status + menu ──\n"
            'INSTALLED=$(( INSTALLED_SYSTEM || INSTALLED_CHROMIUM ))\n'
            "\n"
            'if [ "$HAS_GUI" -eq 1 ]; then\n'
            '    if [ "$INSTALLED" -eq 1 ]; then\n'
            '        CHOICE=$(zenity --list \\\n'
            '            --title="Re-DDNS CA Certificate Tool" \\\n'
            '            --text="$STATUS_ICON  Re-DDNS Root CA\\n\\nStatus:  $STATUS_TEXT\\n\\nWhat would you like to do?" \\\n'
            '            --radiolist --column="" --column="Action" \\\n'
            '            TRUE "Reinstall" \\\n'
            '            FALSE "Remove" \\\n'
            '            --width=450 --height=300 2>/dev/null) || { echo "Cancelled."; exit 0; }\n'
            '    else\n'
            '        CHOICE=$(zenity --list \\\n'
            '            --title="Re-DDNS CA Certificate Tool" \\\n'
            '            --text="$STATUS_ICON  Re-DDNS Root CA\\n\\nStatus:  $STATUS_TEXT\\n\\nInstall the CA certificate to trust all\\n*.reflex-ddns.com HTTPS sites?" \\\n'
            '            --radiolist --column="" --column="Action" \\\n'
            '            TRUE "Install" \\\n'
            '            --width=450 --height=280 2>/dev/null) || { echo "Cancelled."; exit 0; }\n'
            '    fi\n'
            'else\n'
            '    echo "================================================"\n'
            '    echo "$STATUS_ICON  Re-DDNS Root CA"\n'
            '    echo "Status:  $STATUS_TEXT"\n'
            '    echo "================================================"\n'
            '    if [ "$INSTALLED" -eq 1 ]; then\n'
            '        echo ""\n'
            '        echo "  1) Reinstall"\n'
            '        echo "  2) Remove"\n'
            '        echo "  3) Cancel"\n'
            '        read -rp "Choose [1-3]: " pick\n'
            '        case "$pick" in\n'
            '            1) CHOICE="Reinstall" ;;\n'
            '            2) CHOICE="Remove" ;;\n'
            '            *) echo "Cancelled."; exit 0 ;;\n'
            '        esac\n'
            '    else\n'
            '        echo ""\n'
            '        echo "  1) Install"\n'
            '        echo "  2) Cancel"\n'
            '        read -rp "Choose [1-2]: " pick\n'
            '        case "$pick" in\n'
            '            1) CHOICE="Install" ;;\n'
            '            *) echo "Cancelled."; exit 0 ;;\n'
            '        esac\n'
            '    fi\n'
            'fi\n'
            "\n"
            "# ── Execute chosen action ──\n"
            'case "$CHOICE" in\n'
            '    "Install")\n'
            "        do_install \\\n"
            f'            && gui_info "✅ CA certificate installed!\\n\\nAll HTTPS sites under {host} are now trusted.\\nPlease restart Chromium." \\\n'
            '            || gui_error "Installation failed. Please try again."\n'
            "        ;;\n"
            '    "Reinstall")\n'
            "        do_remove 2>/dev/null || true\n"
            "        do_install \\\n"
            f'            && gui_info "✅ CA certificate reinstalled!\\n\\nThe latest certificate for {host} is now active.\\nPlease restart Chromium." \\\n'
            '            || gui_error "Reinstallation failed. Please try again."\n'
            "        ;;\n"
            '    "Remove")\n'
            "        do_remove \\\n"
            '            && gui_info "✅ CA certificate removed.\\n\\nHTTPS sites under *.reflex-ddns.com will no longer be trusted.\\nPlease restart Chromium." \\\n'
            '            || gui_error "Removal failed. The certificate may have been removed already."\n'
            "        ;;\n"
            "    *)\n"
            '        echo "Cancelled."\n'
            "        ;;\n"
            "esac\n"
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
            f'Write-Host "Done! All HTTPS sites under {host} are now trusted."\n'
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
