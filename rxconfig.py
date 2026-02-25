import reflex as rx

config = rx.Config(
    app_name="re_ddns",
    plugins=[rx.plugins.TailwindV3Plugin()],
    # Allow WebSocket / API connections from custom hostnames resolved by
    # the local Docker BIND9 (e.g. home.example.com during dev/testing).
    cors_allowed_origins=[
        "http://home.example.com:3000",
        "http://home.example.com:8000",
        "http://home.example.com",
    ],
)
