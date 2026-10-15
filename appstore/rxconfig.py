import reflex as rx

config = rx.Config(
    app_name="appstore",
    plugins=[
        rx.plugins.TailwindV3Plugin(
            config={
                # The plugin's defaults plus ./app_components, where Reflex 0.10
                # compiles components; without it their classes get no CSS.
                "content": [
                    "./app/**/*.{js,ts,jsx,tsx}",
                    "./utils/**/*.{js,ts,jsx,tsx}",
                    "./app_components/**/*.{js,ts,jsx,tsx}",
                ],
                "plugins": ["@tailwindcss/typography@0.5.20"],
            }
        ),
        rx.plugins.RadixThemesPlugin(theme=rx.theme(appearance="light")),
    ],
    cors_allowed_origins=["*"],
    # The Vite dev server is reached through nginx as aapps.reflex-ddns.com.
    vite_allowed_hosts=True,
)
