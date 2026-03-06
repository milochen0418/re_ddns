"""CA Certificate Installation Guide page.

A dedicated Reflex page that guides users through downloading and
installing the Re-DDNS Local CA root certificate so that all
``*.reflex-ddns.com`` HTTPS sites are trusted by browsers.

Detects the user's OS via JavaScript and highlights the relevant
instructions, with one-click download buttons for the cert and
platform-specific install scripts.
"""

import reflex as rx


class CAGuideState(rx.State):
    """State for the CA installation guide page."""

    selected_os: str = "macos"

    @rx.event
    def select_os(self, os_name: str):
        self.selected_os = os_name


def _os_tab(label: str, icon: str, os_key: str) -> rx.Component:
    is_active = CAGuideState.selected_os == os_key
    return rx.el.button(
        rx.icon(icon, class_name="h-5 w-5"),
        rx.el.span(label),
        on_click=lambda: CAGuideState.select_os(os_key),
        class_name=rx.cond(
            is_active,
            "flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg font-medium shadow-md transition-all",
            "flex items-center gap-2 px-6 py-3 bg-white text-gray-600 rounded-lg font-medium border border-gray-200 hover:bg-gray-50 transition-all",
        ),
    )


def _download_section() -> rx.Component:
    """Step 1: Download the CA certificate."""
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "1",
                    class_name="flex items-center justify-center h-8 w-8 rounded-full bg-blue-600 text-white font-bold text-sm",
                ),
                rx.el.h3(
                    "Download CA Certificate",
                    class_name="text-lg font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-3",
            ),
            rx.el.p(
                "Download the Re-DDNS root certificate. This single file lets your system trust all *.reflex-ddns.com HTTPS sites.",
                class_name="text-gray-600 mt-2 ml-11",
            ),
            rx.el.div(
                rx.el.a(
                    rx.el.button(
                        rx.icon("download", class_name="h-5 w-5"),
                        rx.el.span("Download re_ddns_ca.pem"),
                        class_name="flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-all shadow-md",
                    ),
                    id="ca-download-link",
                    href="/api/ca.pem",
                    download="re_ddns_ca.pem",
                ),
                rx.el.script(
                    """
                    (function() {
                        var el = document.getElementById('ca-download-link');
                        if (el && window.__reddns_api) {
                            el.href = window.__reddns_api('/api/ca.pem');
                        }
                    })();
                    """
                ),
                class_name="mt-4 ml-11",
            ),
            class_name="p-6",
        ),
        class_name="bg-white rounded-xl border border-gray-200 shadow-sm",
    )


def _macos_instructions() -> rx.Component:
    return rx.el.div(
        # Quick method
        rx.el.div(
            rx.el.div(
                rx.icon("zap", class_name="h-5 w-5 text-yellow-500"),
                rx.el.h4(
                    "Quick Install (Terminal)",
                    class_name="font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.p(
                "Run this command in Terminal. It downloads and installs the CA in one step:",
                class_name="text-gray-600 text-sm mt-2",
            ),
            rx.el.div(
                rx.el.code(
                    id="macos-cmd",
                    class_name="text-sm text-green-400",
                ),
                rx.el.script(
                    "document.getElementById('macos-cmd').textContent = "
                    "'curl -sfL http://' + location.host + '/api/ca/install-script/macos | bash';"
                    "if (window.__reddns_api_base) {"
                    "  document.getElementById('macos-cmd').textContent = "
                    "  'curl -sfL ' + window.__reddns_api('/api/ca/install-script/macos') + ' | bash';"
                    "}"
                ),
                class_name="bg-gray-900 rounded-lg p-4 mt-3 overflow-x-auto",
            ),
            rx.el.p(
                "You'll be prompted for your admin password (required by macOS Keychain).",
                class_name="text-gray-500 text-xs mt-2 italic",
            ),
            class_name="p-4 bg-amber-50 rounded-lg border border-amber-200",
        ),
        # Manual method
        rx.el.div(
            rx.el.div(
                rx.icon("hand", class_name="h-5 w-5 text-blue-500"),
                rx.el.h4(
                    "Manual Install",
                    class_name="font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.ol(
                rx.el.li("Download the CA certificate (Step 1 above)"),
                rx.el.li("Double-click the downloaded ", rx.el.code("re_ddns_ca.pem", class_name="text-sm bg-gray-100 px-1 rounded"), " file"),
                rx.el.li("Keychain Access will open → select ", rx.el.strong("System"), " keychain"),
                rx.el.li("Find \"Re-DDNS Root CA\" in the list → double-click it"),
                rx.el.li("Expand ", rx.el.strong("Trust"), " → set \"When using this certificate\" to ", rx.el.strong("Always Trust")),
                rx.el.li("Close the dialog (enter your password to confirm)"),
                rx.el.li("Restart your browser"),
                class_name="list-decimal list-inside text-gray-600 text-sm space-y-2 mt-3",
            ),
            class_name="p-4 mt-3",
        ),
        class_name="space-y-2",
    )


def _windows_instructions() -> rx.Component:
    return rx.el.div(
        # Quick method
        rx.el.div(
            rx.el.div(
                rx.icon("zap", class_name="h-5 w-5 text-yellow-500"),
                rx.el.h4(
                    "Quick Install (PowerShell as Admin)",
                    class_name="font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.p(
                "Open PowerShell as Administrator and run:",
                class_name="text-gray-600 text-sm mt-2",
            ),
            rx.el.div(
                rx.el.code(
                    id="windows-cmd",
                    class_name="text-sm text-green-400",
                ),
                rx.el.script(
                    "document.getElementById('windows-cmd').textContent = "
                    "'Invoke-WebRequest -Uri \"http://' + location.host + '/api/ca/install-script/windows\" '"
                    "+ '-OutFile \"$env:TEMP\\\\install_ca.ps1\"; & \"$env:TEMP\\\\install_ca.ps1\"';"
                    "if (window.__reddns_api_base) {"
                    "  document.getElementById('windows-cmd').textContent = "
                    "  'Invoke-WebRequest -Uri \"' + window.__reddns_api('/api/ca/install-script/windows') + '\" '"
                    "  + '-OutFile \"$env:TEMP\\\\install_ca.ps1\"; & \"$env:TEMP\\\\install_ca.ps1\"';"
                    "}"
                ),
                class_name="bg-gray-900 rounded-lg p-4 mt-3 overflow-x-auto",
            ),
            class_name="p-4 bg-amber-50 rounded-lg border border-amber-200",
        ),
        # Manual method
        rx.el.div(
            rx.el.div(
                rx.icon("hand", class_name="h-5 w-5 text-blue-500"),
                rx.el.h4(
                    "Manual Install",
                    class_name="font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.ol(
                rx.el.li("Download the CA certificate (Step 1 above)"),
                rx.el.li("Double-click the downloaded ", rx.el.code("re_ddns_ca.pem", class_name="text-sm bg-gray-100 px-1 rounded"), " file"),
                rx.el.li("Click ", rx.el.strong("Install Certificate...")),
                rx.el.li("Select ", rx.el.strong("Local Machine"), " → Next"),
                rx.el.li("Select \"Place all certificates in the following store\" → Browse → ", rx.el.strong("Trusted Root Certification Authorities")),
                rx.el.li("Click Next → Finish → confirm the security warning"),
                rx.el.li("Restart your browser"),
                class_name="list-decimal list-inside text-gray-600 text-sm space-y-2 mt-3",
            ),
            class_name="p-4 mt-3",
        ),
        class_name="space-y-2",
    )


def _linux_instructions() -> rx.Component:
    return rx.el.div(
        # Quick method
        rx.el.div(
            rx.el.div(
                rx.icon("zap", class_name="h-5 w-5 text-yellow-500"),
                rx.el.h4(
                    "Quick Install (Terminal)",
                    class_name="font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.p(
                "Run this command (Debian / Ubuntu):",
                class_name="text-gray-600 text-sm mt-2",
            ),
            rx.el.div(
                rx.el.code(
                    id="linux-cmd",
                    class_name="text-sm text-green-400",
                ),
                rx.el.script(
                    "document.getElementById('linux-cmd').textContent = "
                    "'curl -sfL http://' + location.host + '/api/ca/install-script/linux | bash';"
                    "if (window.__reddns_api_base) {"
                    "  document.getElementById('linux-cmd').textContent = "
                    "  'curl -sfL ' + window.__reddns_api('/api/ca/install-script/linux') + ' | bash';"
                    "}"
                ),
                class_name="bg-gray-900 rounded-lg p-4 mt-3 overflow-x-auto",
            ),
            rx.el.p(
                "This installs the CA system-wide for CLI tools (curl, wget). Browsers need separate import — see below.",
                class_name="text-gray-500 text-xs mt-2 italic",
            ),
            class_name="p-4 bg-amber-50 rounded-lg border border-amber-200",
        ),
        # Browser-specific
        rx.el.div(
            rx.el.div(
                rx.icon("globe", class_name="h-5 w-5 text-blue-500"),
                rx.el.h4(
                    "Browser Setup",
                    class_name="font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.div(
                rx.el.p(
                    rx.el.strong("Chrome / Chromium:"),
                    class_name="text-gray-800 text-sm font-medium",
                ),
                rx.el.p(
                    "Settings → Privacy and Security → Security → Manage certificates → Authorities tab → Import → select re_ddns_ca.pem → check all trust options",
                    class_name="text-gray-600 text-sm ml-4",
                ),
                class_name="mt-3",
            ),
            rx.el.div(
                rx.el.p(
                    rx.el.strong("Firefox:"),
                    class_name="text-gray-800 text-sm font-medium",
                ),
                rx.el.p(
                    "Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import → select re_ddns_ca.pem → check \"Trust this CA to identify websites\"",
                    class_name="text-gray-600 text-sm ml-4",
                ),
                class_name="mt-3",
            ),
            class_name="p-4 mt-3",
        ),
        class_name="space-y-2",
    )


def _install_section() -> rx.Component:
    """Step 2: Platform-specific install instructions."""
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "2",
                    class_name="flex items-center justify-center h-8 w-8 rounded-full bg-blue-600 text-white font-bold text-sm",
                ),
                rx.el.h3(
                    "Install on Your Device",
                    class_name="text-lg font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-3",
            ),
            rx.el.p(
                "Select your operating system:",
                class_name="text-gray-600 mt-2 ml-11",
            ),
            # OS tabs
            rx.el.div(
                _os_tab("macOS", "apple", "macos"),
                _os_tab("Windows", "monitor", "windows"),
                _os_tab("Linux", "terminal", "linux"),
                class_name="flex gap-3 mt-4 ml-11 flex-wrap",
            ),
            # Instructions (conditional on selected OS)
            rx.el.div(
                rx.match(
                    CAGuideState.selected_os,
                    ("macos", _macos_instructions()),
                    ("windows", _windows_instructions()),
                    ("linux", _linux_instructions()),
                    _macos_instructions(),
                ),
                class_name="mt-4 ml-11",
            ),
            class_name="p-6",
        ),
        class_name="bg-white rounded-xl border border-gray-200 shadow-sm",
    )


def _verify_section() -> rx.Component:
    """Step 3: Verify it works."""
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "3",
                    class_name="flex items-center justify-center h-8 w-8 rounded-full bg-green-600 text-white font-bold text-sm",
                ),
                rx.el.h3(
                    "Verify",
                    class_name="text-lg font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-3",
            ),
            rx.el.p(
                "After installing the CA, open these URLs — you should see a green lock icon with no warnings:",
                class_name="text-gray-600 mt-2 ml-11",
            ),
            rx.el.div(
                rx.el.a(
                    rx.icon("lock", class_name="h-4 w-4 text-green-600"),
                    rx.el.span(id="verify-url-home"),
                    id="verify-link-home",
                    target="_blank",
                    class_name="flex items-center gap-2 px-4 py-2 bg-green-50 text-green-700 rounded-lg hover:bg-green-100 transition-all text-sm font-mono",
                ),
                rx.el.a(
                    rx.icon("lock", class_name="h-4 w-4 text-green-600"),
                    rx.el.span(id="verify-url-api"),
                    id="verify-link-api",
                    target="_blank",
                    class_name="flex items-center gap-2 px-4 py-2 bg-green-50 text-green-700 rounded-lg hover:bg-green-100 transition-all text-sm font-mono",
                ),
                rx.el.script(
                    """
                    (function() {
                        var h = location.host;
                        var homeUrl = 'https://' + h + '/';
                        var apiUrl  = 'https://' + h + '/api/dns/status';
                        var el1 = document.getElementById('verify-url-home');
                        var lk1 = document.getElementById('verify-link-home');
                        var el2 = document.getElementById('verify-url-api');
                        var lk2 = document.getElementById('verify-link-api');
                        if (el1) el1.textContent = homeUrl;
                        if (lk1) lk1.href = homeUrl;
                        if (el2) el2.textContent = apiUrl;
                        if (lk2) lk2.href = apiUrl;
                    })();
                    """
                ),
                class_name="flex flex-col gap-2 mt-4 ml-11",
            ),
            # "Verify & Switch to HTTPS" button (useful after installing CA)
            rx.el.div(
                rx.el.button(
                    rx.icon("shield-check", class_name="h-5 w-5"),
                    rx.el.span("Verify & Switch to HTTPS"),
                    id="verify-https-btn",
                    class_name="flex items-center gap-2 px-6 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-all shadow-md",
                ),
                rx.el.span(
                    "",
                    id="verify-result",
                    class_name="text-sm ml-3",
                ),
                class_name="mt-4 ml-11 flex items-center",
            ),
            rx.el.script(
                """
                (function() {
                    var btn = document.getElementById('verify-https-btn');
                    var res = document.getElementById('verify-result');
                    if (!btn) return;
                    btn.addEventListener('click', function() {
                        res.textContent = 'Checking...';
                        res.className = 'text-sm ml-3 text-blue-600';
                        fetch(window.__reddns_api
                            ? window.__reddns_api('/api/ca/verify').replace('http:', 'https:')
                            : 'https://' + location.host + '/api/ca/verify',
                            { mode: 'cors' }
                        )
                            .then(function(r) {
                                if (r.ok) {
                                    res.textContent = 'HTTPS works! Redirecting...';
                                    res.className = 'text-sm ml-3 text-green-600 font-medium';
                                    setTimeout(function() {
                                        location.replace('https://' + location.host + '/');
                                    }, 800);
                                } else {
                                    res.textContent = 'HTTPS responded with error. Try restarting your browser.';
                                    res.className = 'text-sm ml-3 text-amber-600';
                                }
                            })
                            .catch(function() {
                                res.textContent = 'HTTPS not working yet. Install the CA certificate and restart your browser.';
                                res.className = 'text-sm ml-3 text-red-600';
                            });
                    });
                })();
                """
            ),
            class_name="p-6",
        ),
        class_name="bg-white rounded-xl border border-gray-200 shadow-sm",
    )


def ca_guide_view() -> rx.Component:
    """Main CA installation guide view."""
    return rx.el.div(
        # ── HTTP warning (hidden by default, shown by JS if on HTTP) ──
        rx.el.div(
            rx.icon("alert-triangle", class_name="h-6 w-6 text-amber-600 flex-shrink-0"),
            rx.el.div(
                rx.el.p(
                    "You're on an insecure HTTP connection",
                    class_name="font-semibold text-amber-800",
                ),
                rx.el.p(
                    "Your browser does not yet trust the Re-DDNS CA certificate. "
                    "Follow the steps below to install it and enable secure HTTPS access.",
                    class_name="text-amber-700 text-sm mt-1",
                ),
            ),
            id="http-warning-banner",
            style={"display": "none"},
            class_name="flex gap-3 p-4 bg-amber-50 rounded-xl border border-amber-300 mb-6",
        ),
        rx.el.script(
            """
            (function() {
                var el = document.getElementById('http-warning-banner');
                if (el && location.protocol === 'http:') {
                    el.style.display = 'flex';
                }
            })();
            """
        ),
        # Header
        rx.el.div(
            rx.el.div(
                rx.icon("shield-check", class_name="h-8 w-8 text-blue-500"),
                rx.el.div(
                    rx.el.h2(
                        "HTTPS Certificate Setup",
                        class_name="text-2xl font-bold text-gray-900",
                    ),
                    rx.el.p(
                        "Install the Re-DDNS CA certificate to enable trusted HTTPS for all *.reflex-ddns.com sites on this network.",
                        class_name="text-gray-500 mt-1",
                    ),
                ),
                class_name="flex items-start gap-4",
            ),
            # Info banner
            rx.el.div(
                rx.icon("info", class_name="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5"),
                rx.el.div(
                    rx.el.p(
                        "This is a one-time setup. Once installed, all current and future *.reflex-ddns.com services will be trusted automatically.",
                        class_name="text-blue-800 text-sm",
                    ),
                ),
                class_name="flex gap-3 p-4 bg-blue-50 rounded-lg border border-blue-200 mt-4",
            ),
            class_name="mb-8",
        ),
        # Steps
        _download_section(),
        _install_section(),
        _verify_section(),
        class_name="max-w-3xl mx-auto space-y-6",
    )
