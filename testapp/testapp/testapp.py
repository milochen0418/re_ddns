"""Test Reflex App – Hello World served via DDNS.

This minimal Reflex application is used to verify that:
1. The re_ddns FastAPI endpoint can register DNS records.
2. The BIND9 DNS server resolves the registered domain.
3. The Reflex app is reachable through that domain name.
"""

import reflex as rx


class TestState(rx.State):
    """Minimal state for the test app."""

    greeting: str = "Hello World from Re-DDNS Test App!"


def index() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            # Header
            rx.el.div(
                rx.el.h1(
                    "Re-DDNS Test App",
                    class_name="text-4xl font-black text-gray-900",
                ),
                rx.el.p(
                    TestState.greeting,
                    class_name="text-lg text-gray-500 mt-2",
                ),
                class_name="text-center mb-12",
            ),
            # Status card
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.el.span("✅", class_name="text-3xl"),
                        class_name="mb-4",
                    ),
                    rx.el.h2(
                        "DNS Resolution Working!",
                        class_name="text-xl font-bold text-green-700 mb-2",
                    ),
                    rx.el.p(
                        "If you can see this page through your custom domain name, "
                        "the DDNS registration via the Re-DDNS API was successful.",
                        class_name="text-gray-600 text-center max-w-md",
                    ),
                    class_name="flex flex-col items-center p-8",
                ),
                class_name="bg-white rounded-2xl border border-green-200 shadow-sm",
            ),
            # Info card
            rx.el.div(
                rx.el.h3(
                    "How it works",
                    class_name="text-lg font-bold text-gray-800 mb-4",
                ),
                rx.el.ul(
                    rx.el.li(
                        "1. This container starts a simple Reflex app.",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "2. On startup, it calls the Re-DDNS API to register a DNS record.",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "3. BIND9 (in the re-ddns container) now resolves the domain.",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "4. You can access this page via the registered domain name.",
                        class_name="text-gray-600 mb-2",
                    ),
                    class_name="list-none space-y-1",
                ),
                class_name="bg-white rounded-2xl border border-gray-200 shadow-sm p-8 mt-6",
            ),
            class_name="max-w-2xl mx-auto py-20 px-6",
        ),
        class_name="min-h-screen bg-gray-50 font-['Inter']",
    )


app = rx.App(
    theme=rx.theme(appearance="light"),
    head_components=[
        rx.el.link(rel="preconnect", href="https://fonts.googleapis.com"),
        rx.el.link(
            rel="preconnect", href="https://fonts.gstatic.com", cross_origin=""
        ),
        rx.el.link(
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap",
            rel="stylesheet",
        ),
    ],
)
app.add_page(index)
