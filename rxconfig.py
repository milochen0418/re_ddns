import reflex as rx

config = rx.Config(
    app_name="re_ddns",
    plugins=[rx.plugins.TailwindV3Plugin()],
    # Allow WebSocket / API connections from custom hostnames resolved by
    # the local Docker BIND9 (e.g. home.reflex-ddns.com during dev/testing).
    # "*" permits all origins — safe for a LAN-only DDNS tool.
    cors_allowed_origins=["*"],
)
