import os

import reflex as rx

config = rx.Config(
    app_name="re_ddns",
    plugins=[rx.plugins.TailwindV3Plugin()],
    # When behind nginx (Docker), API_URL points to the nginx port so the
    # browser connects via ws://home.reflex-ddns.com/_event (port 80/443)
    # rather than attempting port 8000 which is not exposed.
    api_url=os.getenv("API_URL", "http://localhost:8000"),
    # Allow WebSocket / API connections from custom hostnames resolved by
    # the local Docker BIND9 (e.g. home.reflex-ddns.com during dev/testing).
    # "*" permits all origins — safe for a LAN-only DDNS tool.
    cors_allowed_origins=["*"],
)
