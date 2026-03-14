import reflex as rx

config = rx.Config(
    app_name="testapp",
    plugins=[rx.plugins.TailwindV3Plugin()],
    cors_allowed_origins=["*"],
)
