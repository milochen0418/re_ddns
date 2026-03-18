"""Dynamic nginx reverse-proxy configuration manager (HTTP + HTTPS).

All configuration is **derived from the service registry** and the
certificate store.  This module never stores state itself.

When a TLS certificate exists for a domain (checked via
``cert_manager.has_cert()``), the generated nginx config will:
  1. Listen on **:443 ssl** with the cert.
  2. Redirect **:80** to HTTPS (except the ACME challenge path).

When no certificate exists, the config serves on **:80** only and
exposes ``/.well-known/acme-challenge/`` so certbot can work later.

Generated files live under ``/etc/nginx/conf.d/``:
  - ``_base.conf``        – globals, SSL params, re-ddns server blocks, fallback
  - ``<subdomain>.conf``  – one per registered service
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from re_ddns.api import cert_manager, registry_api

logger = logging.getLogger(__name__)

NGINX_CONF_DIR = Path("/etc/nginx/conf.d")
BASE_CONF = NGINX_CONF_DIR / "_base.conf"

# ACME challenge webroot (shared with cert_manager)
ACME_WEBROOT = "/var/www/acme"

# Reflex internal paths that must be proxied to the *backend* (FastAPI) port.
# Everything else goes to the *frontend* (Vite / static) port.
_REFLEX_BACKEND_PATHS = ("/_event", "/ping", "/_upload", "/_health", "/api")


# =====================================================================
# Building blocks – small helpers that compose into full server blocks
# =====================================================================

def _acme_location() -> str:
    """Snippet: serve ACME HTTP-01 challenges on port 80."""
    return (
        "    location /.well-known/acme-challenge/ {\n"
        f"        root {ACME_WEBROOT};\n"
        "    }\n"
    )


def _proxy_location(upstream: str, path: str = "/") -> str:
    """Snippet: reverse-proxy location block for *path* → *upstream*."""
    return (
        f"    location {path} {{\n"
        f"        proxy_pass http://{upstream};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host              $host;\n"
        "        proxy_set_header X-Real-IP         $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header Upgrade    $http_upgrade;\n"
        "        proxy_set_header Connection $connection_upgrade;\n"
        "        proxy_read_timeout 86400s;\n"
        "    }\n"
    )


def _proxy_location_var(var_name: str, path: str = "/") -> str:
    """Snippet: reverse-proxy location using a variable (lazy DNS resolve).

    When ``proxy_pass`` uses a variable, nginx resolves the hostname at
    request time (via the ``resolver`` directive) instead of at startup.
    This means nginx can start even if the upstream host does not exist.
    """
    return (
        f"    location {path} {{\n"
        f"        proxy_pass http://${var_name};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host              $host;\n"
        "        proxy_set_header X-Real-IP         $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header Upgrade    $http_upgrade;\n"
        "        proxy_set_header Connection $connection_upgrade;\n"
        "        proxy_read_timeout 86400s;\n"
        "    }\n"
    )


def _reflex_proxy_locations(
    frontend_upstream: str,
    backend_upstream: str,
) -> str:
    """Location blocks with path-based routing for a Reflex app.

    Reflex internal paths (``/_event``, ``/ping``, …) are proxied to the
    *backend* (FastAPI) upstream, while everything else goes to the
    *frontend* (Vite / static) upstream.
    """
    parts: list[str] = []
    for p in _REFLEX_BACKEND_PATHS:
        parts.append(_proxy_location(backend_upstream, p))
    parts.append(_proxy_location(frontend_upstream))
    return "\n".join(parts)


def _ssl_directives(domain: str) -> str:
    """Snippet: ssl_certificate + ssl_certificate_key lines."""
    d = cert_manager.cert_dir(domain)
    return (
        f"    ssl_certificate     {d}/fullchain.pem;\n"
        f"    ssl_certificate_key {d}/privkey.pem;\n"
    )


def _server_blocks(
    domain: str,
    upstream: str,
    *,
    backend_upstream: str | None = None,
    is_default: bool = False,
    http_redirect: bool = True,
) -> str:
    """Generate HTTP + optional HTTPS server blocks for *domain*.

    If a cert exists → HTTP redirects to HTTPS; HTTPS serves content.
    If no cert        → HTTP serves content directly.
    """
    has_ssl = cert_manager.has_cert(domain)

    sn = "_" if is_default else domain
    listen_80 = "    listen 80 default_server;" if is_default else "    listen 80;"
    listen_443 = "    listen 443 ssl http2 default_server;" if is_default else "    listen 443 ssl http2;"

    parts: list[str] = []

    # ── HTTP server block ──
    parts.append("server {")
    parts.append(listen_80)
    parts.append(f"    server_name {sn};")
    parts.append("")
    # Choose location blocks: dual (frontend + backend) or single upstream
    if backend_upstream:
        locations = _reflex_proxy_locations(upstream, backend_upstream)
    else:
        locations = _proxy_location(upstream)

    parts.append(_acme_location())
    if has_ssl and http_redirect:
        # Redirect everything else to HTTPS
        parts.append("    location / {")
        parts.append("        return 301 https://$host$request_uri;")
        parts.append("    }")
    else:
        # Serve directly (HTTP-only or HTTP kept as CA-check fallback)
        parts.append(locations)
    parts.append("}")
    parts.append("")

    # ── HTTPS server block (only if cert exists) ──
    if has_ssl:
        parts.append("server {")
        parts.append(listen_443)
        parts.append(f"    server_name {sn};")
        parts.append("")
        parts.append(_ssl_directives(domain))
        parts.append("")
        parts.append(locations)
        parts.append("}")
        parts.append("")

    return "\n".join(parts)


def _server_blocks_resolver(
    domain: str,
    sub: str,
    fe_target: str,
    be_target: str,
) -> str:
    """Generate server blocks using variable-based proxy_pass.

    Unlike ``_server_blocks`` which uses named upstream groups, this
    version sets ``$fe_<sub>`` and ``$be_<sub>`` variables and uses the
    Docker embedded DNS resolver (127.0.0.11) so that nginx can start
    even when the upstream container does not yet exist.
    """
    has_ssl = cert_manager.has_cert(domain)

    fe_var = f"fe_{sub.replace('-', '_')}"
    be_var = f"be_{sub.replace('-', '_')}"

    # Build resolver-based location blocks
    def _locations() -> str:
        parts: list[str] = []
        for p in _REFLEX_BACKEND_PATHS:
            parts.append(_proxy_location_var(be_var, p))
        parts.append(_proxy_location_var(fe_var))
        return "\n".join(parts)

    set_vars = (
        f"    set ${fe_var} {fe_target};\n"
        f"    set ${be_var} {be_target};\n"
    )

    parts: list[str] = []

    # ── HTTP server block ──
    parts.append("server {")
    parts.append("    listen 80;")
    parts.append(f"    server_name {domain};")
    parts.append("")
    parts.append("    resolver 127.0.0.11 valid=10s;")
    parts.append(set_vars)
    parts.append(_acme_location())
    if has_ssl:
        parts.append("    location / {")
        parts.append("        return 301 https://$host$request_uri;")
        parts.append("    }")
    else:
        parts.append(_locations())
    parts.append("}")
    parts.append("")

    # ── HTTPS server block (only if cert exists) ──
    if has_ssl:
        parts.append("server {")
        parts.append("    listen 443 ssl http2;")
        parts.append(f"    server_name {domain};")
        parts.append("")
        parts.append(_ssl_directives(domain))
        parts.append("")
        parts.append("    resolver 127.0.0.11 valid=10s;")
        parts.append(set_vars)
        parts.append(_locations())
        parts.append("}")
        parts.append("")

    return "\n".join(parts)


# =====================================================================
# Full config generators
# =====================================================================

def _base_config_content() -> str:
    """Return the base nginx config with SSL params, upstreams, and
    server blocks for home / api / fallback.
    """
    lines: list[str] = [
        "# Auto-generated by re_ddns – do not edit manually",
        "",
        "# ── WebSocket upgrade support ──",
        "map $http_upgrade $connection_upgrade {",
        "    default upgrade;",
        "    ''      close;",
        "}",
        "",
        "# ── SSL settings (shared via main nginx.conf) ──",
        "# Note: ssl_protocols and ssl_prefer_server_ciphers are set in",
        "# /etc/nginx/nginx.conf; only add non-duplicate directives here.",
        "ssl_session_cache shared:SSL:10m;",
        "ssl_session_timeout 1d;",
        "",
        "# ── re-ddns upstreams ──",
        "upstream _re_ddns_frontend {",
        "    server 127.0.0.1:3000;",
        "}",
        "",
        "upstream _re_ddns_backend {",
        "    server 127.0.0.1:8000;",
        "}",
        "",
        "# ── home.reflex-ddns.com (HTTP kept open for CA-check fallback) ──",
        _server_blocks(
            "home.reflex-ddns.com", "_re_ddns_frontend",
            backend_upstream="_re_ddns_backend", http_redirect=False,
        ),
        "# ── api.reflex-ddns.com (HTTP kept open for CA download) ──",
        _server_blocks("api.reflex-ddns.com", "_re_ddns_backend", http_redirect=False),
        "# ── Fallback: unknown Host → re-ddns UI ──",
        _server_blocks(
            "reflex-ddns.com", "_re_ddns_frontend",
            backend_upstream="_re_ddns_backend", is_default=True,
        ),
    ]
    return "\n".join(lines) + "\n"


def _service_config(svc: dict) -> str:
    """Generate nginx config for one registered service.

    Uses variable-based proxy_pass with a resolver instead of static
    ``upstream`` blocks.  This allows nginx to start even when the
    upstream container does not exist yet (or has been removed).
    Requests to a missing upstream will return 502 instead of crashing
    nginx at startup.
    """
    fqdn = f"{svc['subdomain']}.{svc['zone']}"
    sub = svc["subdomain"]
    host = svc["upstream_host"]
    fe_port = svc["frontend_port"]
    be_port = svc.get("backend_port", 8000)

    fe_target = f"{host}:{fe_port}"
    be_target = f"{host}:{be_port}"

    lines: list[str] = [
        f"# Auto-generated by re_ddns for {fqdn}",
        "",
        _server_blocks_resolver(fqdn, sub, fe_target, be_target),
    ]
    return "\n".join(lines)


def _manual_cname_config(rec: dict) -> str:
    """Generate nginx proxy config for a manual CNAME record.

    Inside the Docker network all ``*.reflex-ddns.com`` queries resolve to
    the re-ddns container.  Without an explicit nginx server block, CNAME
    manual records would hit the default server and show the re-ddns UI
    instead of the external target.  This function generates a pass-through
    proxy so that requests are forwarded to the real CNAME target.
    """
    subdomain = rec["subdomain"]
    zone = rec.get("zone", "reflex-ddns.com")
    fqdn = f"{subdomain}.{zone}"
    # Strip the trailing DNS dot from the CNAME target
    target = rec["ip_address"].rstrip(".")

    var = f"cname_{subdomain.replace('-', '_')}"

    parts: list[str] = [
        f"# Auto-generated CNAME proxy for {fqdn} -> {target}",
        "",
        "server {",
        "    listen 80;",
        f"    server_name {fqdn};",
        "",
        "    resolver 127.0.0.11 valid=30s;",
        f"    set ${var} {target};",
        "",
        "    location / {",
        f"        proxy_pass https://${var};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host              $proxy_host;",
        "        proxy_set_header X-Real-IP         $remote_addr;",
        "        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "        proxy_ssl_server_name on;",
        "    }",
        "}",
        "",
        "server {",
        "    listen 443 ssl http2;",
        f"    server_name {fqdn};",
        "",
    ]

    if cert_manager.has_cert(fqdn):
        parts.append(_ssl_directives(fqdn))
    else:
        # Use the fallback / default cert so TLS still works
        if cert_manager.has_cert("reflex-ddns.com"):
            parts.append(_ssl_directives("reflex-ddns.com"))

    parts += [
        "",
        "    resolver 127.0.0.11 valid=30s;",
        f"    set ${var} {target};",
        "",
        "    location / {",
        f"        proxy_pass https://${var};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host              $proxy_host;",
        "        proxy_set_header X-Real-IP         $remote_addr;",
        "        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "        proxy_ssl_server_name on;",
        "    }",
        "}",
        "",
    ]
    return "\n".join(parts)


# =====================================================================
# Public API
# =====================================================================

def write_base_config() -> None:
    """Write the base nginx config (called once at startup)."""
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    BASE_CONF.write_text(_base_config_content())
    logger.info("Wrote base nginx config: %s", BASE_CONF)


def sync() -> bool:
    """Regenerate **all** nginx configs from the registry and reload.

    1. Rewrite ``_base.conf`` (cert availability may have changed).
    2. Write a ``.conf`` per registered service.
    3. Remove stale ``.conf`` files.
    4. ``nginx -t && nginx -s reload``.

    Returns *True* on success.
    """
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)

    # Re-generate base config (picks up new certs for home/api)
    BASE_CONF.write_text(_base_config_content())

    services = registry_api.list_services()
    wanted_files: set[str] = set()

    for svc in services:
        fname = f"{svc['subdomain']}.conf"
        wanted_files.add(fname)
        conf_path = NGINX_CONF_DIR / fname
        conf_path.write_text(_service_config(svc))
        logger.info("Wrote nginx config: %s", conf_path)

    # Write proxy configs for CNAME manual records (so Docker-internal
    # requests are forwarded to the real external target).
    for rec in registry_api.list_manual_records():
        if rec.get("record_type") != "CNAME":
            continue
        fname = f"manual-{rec['subdomain']}.conf"
        wanted_files.add(fname)
        conf_path = NGINX_CONF_DIR / fname
        conf_path.write_text(_manual_cname_config(rec))
        logger.info("Wrote CNAME proxy config: %s", conf_path)

    # Remove stale configs (skip _base.conf and system files)
    for existing in NGINX_CONF_DIR.glob("*.conf"):
        if existing.name.startswith("_"):
            continue
        if existing.name not in wanted_files:
            existing.unlink()
            logger.info("Removed stale nginx config: %s", existing)

    return reload_nginx()


def reload_nginx() -> bool:
    """Test config and reload nginx.  Returns *True* on success."""
    try:
        result = subprocess.run(
            ["nginx", "-t"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.error("nginx config test failed:\n%s", result.stderr)
            return False

        result = subprocess.run(
            ["nginx", "-s", "reload"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.error("nginx reload failed:\n%s", result.stderr)
            return False

        logger.info("nginx reloaded successfully")
        return True
    except Exception as exc:
        logger.exception("Failed to reload nginx: %s", exc)
        return False
