"""Test Reflex App 2 – Browser-enabled DDNS test container.

This Reflex application is used to verify that:
1. The re_ddns FastAPI endpoint can register DNS records.
2. The BIND9 DNS server resolves the registered domain.
3. A browser running INSIDE this container can reach the re-ddns UI.
4. The browser can download and install the CA certificate.
5. HTTPS works end-to-end from a remote machine's browser.

Access the in-container browser via noVNC:
    http://localhost:6080/vnc.html
"""

import reflex as rx


class TestState(rx.State):
    """Minimal state for testapp2."""

    greeting: str = "Hello from TestApp2 – Browser-Enabled Test Container!"


def index() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            # Header
            rx.el.div(
                rx.el.h1(
                    "Re-DDNS TestApp2",
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
                        rx.el.span("🖥️", class_name="text-3xl"),
                        class_name="mb-4",
                    ),
                    rx.el.h2(
                        "Browser-Enabled Test Container",
                        class_name="text-xl font-bold text-blue-700 mb-2",
                    ),
                    rx.el.p(
                        "This container runs Chromium with noVNC. "
                        "Access the browser from your Mac at ",
                        rx.el.code(
                            "http://localhost:6080/vnc.html",
                            class_name="bg-gray-100 px-2 py-1 rounded text-sm",
                        ),
                        class_name="text-gray-600 text-center max-w-md",
                    ),
                    class_name="flex flex-col items-center p-8",
                ),
                class_name="bg-white rounded-2xl border border-blue-200 shadow-sm",
            ),
            # Capabilities card
            rx.el.div(
                rx.el.h3(
                    "Test capabilities",
                    class_name="text-lg font-bold text-gray-800 mb-4",
                ),
                rx.el.ul(
                    rx.el.li(
                        "1. DNS registration with re-ddns (same as testapp1).",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "2. In-container Chromium browser (viewable via noVNC).",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "3. Download CA certificate from re-ddns UI.",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "4. Install CA cert in Chromium / system trust store.",
                        class_name="text-gray-600 mb-2",
                    ),
                    rx.el.li(
                        "5. Verify HTTPS works end-to-end from a remote browser.",
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
