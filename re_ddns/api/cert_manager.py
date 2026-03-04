"""TLS certificate manager.

Supports two modes (controlled by the ``TLS_MODE`` env var):

- **self-signed** (default) – instantly generates a self-signed cert via
  ``openssl`` for each registered domain.  Perfect for local dev / Docker.
- **letsencrypt** – obtains a real certificate from Let's Encrypt using the
  HTTP-01 challenge (requires a public IP and DNS already pointing here).

Certficates are stored under ``/app/data/certs/<domain>/``:
  - ``fullchain.pem``
  - ``privkey.pem``

Usage::

    from re_ddns.api import cert_manager

    cert_manager.init()                          # once at startup
    cert_manager.ensure_cert("app.example.com")  # generates / obtains cert
    cert_manager.has_cert("app.example.com")     # → True
    cert_manager.cert_dir("app.example.com")     # → Path(…)
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CERT_BASE_DIR = Path("/app/data/certs")
ACME_WEBROOT = Path("/var/www/acme")

# "self-signed" | "letsencrypt" | "none"
TLS_MODE: str = os.environ.get("TLS_MODE", "self-signed")

LETSENCRYPT_EMAIL: str = os.environ.get("LETSENCRYPT_EMAIL", "")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def init() -> None:
    """Create directories.  Call once at startup."""
    CERT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    ACME_WEBROOT.mkdir(parents=True, exist_ok=True)
    logger.info("cert_manager init: TLS_MODE=%s, certs dir=%s", TLS_MODE, CERT_BASE_DIR)


def cert_dir(domain: str) -> Path:
    """Return the directory where cert files for *domain* are stored."""
    return CERT_BASE_DIR / domain


def has_cert(domain: str) -> bool:
    """Return *True* if both fullchain and privkey exist for *domain*."""
    d = cert_dir(domain)
    return (d / "fullchain.pem").is_file() and (d / "privkey.pem").is_file()


def ensure_cert(domain: str) -> bool:
    """Generate or obtain a certificate for *domain*.

    Returns *True* on success.  Idempotent — skips if cert already exists.
    """
    if TLS_MODE == "none":
        logger.debug("TLS_MODE=none — skipping cert for %s", domain)
        return False

    if has_cert(domain):
        logger.debug("Cert already exists for %s — skipping", domain)
        return True

    if TLS_MODE == "letsencrypt":
        return _obtain_letsencrypt(domain)

    # Default: self-signed
    return _generate_self_signed(domain)


# ---------------------------------------------------------------------------
# Self-signed (openssl)
# ---------------------------------------------------------------------------

def _generate_self_signed(domain: str) -> bool:
    """Generate a self-signed certificate valid for 825 days."""
    d = cert_dir(domain)
    d.mkdir(parents=True, exist_ok=True)

    key_path = d / "privkey.pem"
    cert_path = d / "fullchain.pem"

    try:
        result = subprocess.run(
            [
                "openssl", "req",
                "-x509", "-nodes",
                "-days", "825",
                "-newkey", "rsa:2048",
                "-keyout", str(key_path),
                "-out", str(cert_path),
                "-subj", f"/CN={domain}",
                "-addext", f"subjectAltName=DNS:{domain}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error("openssl failed for %s:\n%s", domain, result.stderr)
            return False

        logger.info("Generated self-signed cert for %s", domain)
        return True

    except Exception as exc:
        logger.exception("Self-signed cert generation error for %s: %s", domain, exc)
        return False


# ---------------------------------------------------------------------------
# Let's Encrypt (certbot HTTP-01)
# ---------------------------------------------------------------------------

def _obtain_letsencrypt(domain: str) -> bool:
    """Obtain a certificate via certbot's HTTP-01 challenge.

    Prerequisites:
      - nginx must be running and serving ``/.well-known/acme-challenge/``
        from ``/var/www/acme`` on port 80 for this domain.
      - The domain must resolve to this server's public IP.
    """
    email_args: list[str] = []
    if LETSENCRYPT_EMAIL:
        email_args = ["-m", LETSENCRYPT_EMAIL]
    else:
        email_args = ["--register-unsafely-without-email"]

    try:
        result = subprocess.run(
            [
                "certbot", "certonly",
                "--webroot",
                "-w", str(ACME_WEBROOT),
                "-d", domain,
                "--non-interactive",
                "--agree-tos",
                *email_args,
                # Use the default /etc/letsencrypt location, then symlink
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("certbot failed for %s:\n%s\n%s",
                         domain, result.stdout, result.stderr)
            return False

        # Symlink from /etc/letsencrypt/live/<domain>/ → our cert dir
        le_live = Path(f"/etc/letsencrypt/live/{domain}")
        d = cert_dir(domain)
        d.mkdir(parents=True, exist_ok=True)

        for fname in ("fullchain.pem", "privkey.pem"):
            dest = d / fname
            dest.unlink(missing_ok=True)
            dest.symlink_to(le_live / fname)

        logger.info("Obtained Let's Encrypt cert for %s", domain)
        return True

    except FileNotFoundError:
        logger.error("certbot not found — install it or switch TLS_MODE to self-signed")
        return False
    except Exception as exc:
        logger.exception("Let's Encrypt error for %s: %s", domain, exc)
        return False
