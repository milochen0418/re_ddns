"""TLS certificate manager — **Local CA** mode.

Instead of generating independent self-signed certs per domain, this
module creates a **local Certificate Authority (CA)** once and uses it
to sign certificates for every registered domain.

Users only need to install the CA root certificate (``ca.pem``) once on
their device, and all ``*.reflex-ddns.com`` HTTPS sites will be trusted
with a green lock icon — no per-domain warnings.

Modes (controlled by ``TLS_MODE`` env var):

- **local-ca** (default) – generate a local CA, sign domain certs with it.
  Perfect for LAN / Docker dev.
- **letsencrypt** – obtain real certificates from Let's Encrypt (HTTP-01).
  Requires a public IP.
- **none** – no TLS certificates; HTTP only.

Certificate layout::

    /app/data/certs/
    ├── _ca/
    │   ├── ca.pem           ← Root cert (distribute to clients)
    │   └── ca-key.pem       ← Private key (never leaves the server)
    ├── home.reflex-ddns.com/
    │   ├── fullchain.pem
    │   └── privkey.pem
    └── testapp.reflex-ddns.com/
        ├── fullchain.pem
        └── privkey.pem
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CERT_BASE_DIR = Path("/app/data/certs")
CA_DIR = CERT_BASE_DIR / "_ca"
CA_KEY = CA_DIR / "ca-key.pem"
CA_CERT = CA_DIR / "ca.pem"
CA_SERIAL = CA_DIR / "ca.srl"
ACME_WEBROOT = Path("/var/www/acme")

# "local-ca" | "letsencrypt" | "none"
TLS_MODE: str = os.environ.get("TLS_MODE", "local-ca")

LETSENCRYPT_EMAIL: str = os.environ.get("LETSENCRYPT_EMAIL", "")

# CA subject — used when generating the root certificate
CA_SUBJECT: str = os.environ.get(
    "CA_SUBJECT",
    "/C=TW/O=Re-DDNS Local CA/CN=Re-DDNS Root CA",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init() -> None:
    """Create directories and ensure the CA exists.  Call once at startup."""
    CERT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    ACME_WEBROOT.mkdir(parents=True, exist_ok=True)

    if TLS_MODE == "local-ca":
        _ensure_ca()

    logger.info("cert_manager init: TLS_MODE=%s, certs_dir=%s", TLS_MODE, CERT_BASE_DIR)


def cert_dir(domain: str) -> Path:
    """Return the directory where cert files for *domain* live."""
    return CERT_BASE_DIR / domain


def has_cert(domain: str) -> bool:
    """Return *True* if both fullchain and privkey exist for *domain*."""
    d = cert_dir(domain)
    return (d / "fullchain.pem").is_file() and (d / "privkey.pem").is_file()


def has_ca() -> bool:
    """Return *True* if the local CA root cert exists."""
    return CA_CERT.is_file() and CA_KEY.is_file()


def ca_pem_bytes() -> bytes:
    """Return the CA root certificate as bytes (for download)."""
    if not CA_CERT.is_file():
        return b""
    return CA_CERT.read_bytes()


def ca_fingerprint() -> str:
    """Return the SHA-256 fingerprint of the CA root certificate.

    Used by clients to detect when the CA has been regenerated so they
    know to re-install the new root cert.
    """
    if not CA_CERT.is_file():
        return ""
    pem = CA_CERT.read_bytes()
    return f"sha256:{hashlib.sha256(pem).hexdigest()}"


def ensure_cert(domain: str) -> bool:
    """Generate or obtain a cert for *domain*.  Idempotent.

    Returns *True* on success.
    """
    if TLS_MODE == "none":
        logger.debug("TLS_MODE=none — skipping cert for %s", domain)
        return False

    if has_cert(domain):
        logger.debug("Cert already exists for %s — skipping", domain)
        return True

    if TLS_MODE == "letsencrypt":
        return _obtain_letsencrypt(domain)

    # Default: local-ca (also covers legacy "self-signed" value)
    return _sign_with_local_ca(domain)


# ---------------------------------------------------------------------------
# Local CA management
# ---------------------------------------------------------------------------

def _ensure_ca() -> None:
    """Generate the root CA key + cert if they don't already exist."""
    if has_ca():
        logger.info("Local CA already exists: %s", CA_CERT)
        return

    CA_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Generate CA private key
    _run_openssl([
        "openssl", "genrsa", "-out", str(CA_KEY), "4096",
    ], "generate CA key")

    # 2) Generate self-signed CA root certificate (10 years)
    _run_openssl([
        "openssl", "req", "-x509", "-new", "-nodes",
        "-key", str(CA_KEY),
        "-sha256",
        "-days", "3650",
        "-out", str(CA_CERT),
        "-subj", CA_SUBJECT,
    ], "generate CA root cert")

    logger.info("Created local CA: %s", CA_CERT)


def _sign_with_local_ca(domain: str) -> bool:
    """Generate a domain certificate signed by the local CA."""
    if not has_ca():
        logger.error("Local CA not initialised — cannot sign cert for %s", domain)
        return False

    d = cert_dir(domain)
    d.mkdir(parents=True, exist_ok=True)

    key_path = d / "privkey.pem"
    csr_path = d / "domain.csr"
    cert_path = d / "fullchain.pem"
    ext_path = d / "openssl.ext"

    # Extension file for SAN
    ext_path.write_text(
        "authorityKeyIdentifier=keyid,issuer\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment\n"
        "subjectAltName = @alt_names\n"
        "\n"
        "[alt_names]\n"
        f"DNS.1 = {domain}\n"
    )

    try:
        # 1) Generate domain private key
        _run_openssl([
            "openssl", "genrsa", "-out", str(key_path), "2048",
        ], f"generate key for {domain}")

        # 2) Generate CSR
        _run_openssl([
            "openssl", "req", "-new",
            "-key", str(key_path),
            "-out", str(csr_path),
            "-subj", f"/CN={domain}",
        ], f"generate CSR for {domain}")

        # 3) Sign with CA (valid 825 days)
        _run_openssl([
            "openssl", "x509", "-req",
            "-in", str(csr_path),
            "-CA", str(CA_CERT),
            "-CAkey", str(CA_KEY),
            "-CAcreateserial",
            "-out", str(cert_path),
            "-days", "825",
            "-sha256",
            "-extfile", str(ext_path),
        ], f"sign cert for {domain}")

        # Cleanup intermediate files
        csr_path.unlink(missing_ok=True)
        ext_path.unlink(missing_ok=True)

        logger.info("Signed cert for %s with local CA", domain)
        return True

    except Exception as exc:
        logger.exception("Failed to sign cert for %s: %s", domain, exc)
        return False


# ---------------------------------------------------------------------------
# Let's Encrypt (certbot HTTP-01)
# ---------------------------------------------------------------------------

def _obtain_letsencrypt(domain: str) -> bool:
    """Obtain a certificate via certbot's HTTP-01 challenge."""
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
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error("certbot failed for %s:\n%s\n%s",
                         domain, result.stdout, result.stderr)
            return False

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
        logger.error("certbot not found — switch TLS_MODE to local-ca")
        return False
    except Exception as exc:
        logger.exception("Let's Encrypt error for %s: %s", domain, exc)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_openssl(cmd: list[str], description: str) -> None:
    """Run an openssl command, raising on failure."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"openssl ({description}) failed:\n{result.stderr}"
        )
