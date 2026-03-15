#!/usr/bin/env python3
"""Register this test-app as a service in re-ddns.

Called once by entrypoint.sh before starting the Reflex dev server.

A single ``POST /api/service/register`` call tells re-ddns to:
  1. Write the service to ``registry.json``.
  2. Generate an nginx reverse-proxy config and reload nginx.
  3. Create a DNS A record in BIND9.

The test-app does NOT need TSIG credentials — re-ddns uses its own
server-side key automatically.

Environment variables (all optional — sensible defaults provided):
    RE_DDNS_API_URL      – base URL of the re-ddns backend  (http://re-ddns:8000)
    SERVICE_SUBDOMAIN    – subdomain to register             (testapp3)
    SERVICE_ZONE         – DNS zone                          (reflex-ddns.com)
    SERVICE_IP           – IP the A record should point to   (127.0.0.1)
"""

from __future__ import annotations

import os
import socket
import sys
import time

import httpx

API_URL = os.environ.get("RE_DDNS_API_URL", "http://re-ddns:8000")
SUBDOMAIN = os.environ.get("SERVICE_SUBDOMAIN", "testapp3")
ZONE = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
# Docker service name / hostname — defaults to the container hostname
UPSTREAM_HOST = os.environ.get("SERVICE_UPSTREAM_HOST", socket.gethostname())


def _detect_container_ip() -> str:
    """Auto-detect the container's network IP for DNS registration."""
    # 1. Explicit env var overrides auto-detection
    env_ip = os.environ.get("SERVICE_IP", "")
    if env_ip:
        return env_ip
    # 2. Resolve own hostname → Docker assigns the container network IP
    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        pass
    # 3. Fallback
    return "127.0.0.1"


IP = _detect_container_ip()


def wait_for_api(url: str, retries: int = 30, delay: float = 2.0) -> bool:
    """Block until the re-ddns API responds to GET /api/dns/status."""
    endpoint = f"{url}/api/dns/status"
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(endpoint, timeout=5.0)
            if r.status_code == 200:
                print(f"[register] re-ddns API is ready (attempt {attempt})")
                return True
        except httpx.RequestError:
            pass
        print(f"[register] Waiting for re-ddns API … ({attempt}/{retries})")
        time.sleep(delay)
    return False


def register_service() -> bool:
    """POST /api/service/register — one call does DNS + nginx."""
    payload = {
        "subdomain": SUBDOMAIN,
        "zone_name": ZONE,
        "upstream_host": UPSTREAM_HOST,
        "frontend_port": 3000,
        "backend_port": 8000,
        "ip_address": IP,
        "ttl": 60,
    }
    endpoint = f"{API_URL}/api/service/register"
    print(f"[register] POST {endpoint}")
    print(f"[register]   {SUBDOMAIN}.{ZONE} -> upstream={UPSTREAM_HOST}, dns={IP}")

    try:
        r = httpx.post(endpoint, json=payload, timeout=15.0)
        data = r.json()
        print(f"[register] Response: {data}")
        return data.get("success", False)
    except Exception as exc:
        print(f"[register] ERROR: {exc}", file=sys.stderr)
        return False


def main() -> None:
    if not wait_for_api(API_URL):
        print("[register] ERROR: re-ddns API did not become ready.", file=sys.stderr)
        sys.exit(1)

    ok = register_service()
    if ok:
        print("[register] DNS registration successful!")
    else:
        print("[register] WARNING: DNS registration returned failure.", file=sys.stderr)


if __name__ == "__main__":
    main()
