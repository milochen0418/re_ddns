"""Advanced DNS page component.

Provides a form to execute arbitrary RFC 2136 dynamic DNS updates
with full record-type support (A, AAAA, CNAME, MX, TXT, NS, SRV, PTR, CAA).
"""

import reflex as rx
from re_ddns.states.advanced_dns_state import AdvancedDNSState


# ── Record-type options ──────────────────────────────────────────────

_TYPE_OPTIONS = [
    ("A", "A — IPv4 Address"),
    ("AAAA", "AAAA — IPv6 Address"),
    ("CNAME", "CNAME — Canonical Name"),
    ("MX", "MX — Mail Exchange"),
    ("TXT", "TXT — Text Record"),
    ("NS", "NS — Nameserver"),
    ("SRV", "SRV — Service Locator"),
    ("PTR", "PTR — Pointer"),
    ("CAA", "CAA — Certification Authority"),
]


# ── Reusable helpers ─────────────────────────────────────────────────

def _label(text: str) -> rx.Component:
    return rx.el.label(text, class_name="block text-sm font-semibold text-gray-700 mb-1.5")


def _input(attr: str, placeholder: str, **kw) -> rx.Component:
    return rx.el.input(
        value=getattr(AdvancedDNSState, attr),
        on_change=getattr(AdvancedDNSState, f"set_{attr}"),
        placeholder=placeholder,
        class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl "
                   "focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none "
                   "transition-all hover:border-gray-300",
        **kw,
    )


def _field(label: str, attr: str, placeholder: str, **kw) -> rx.Component:
    return rx.el.div(
        _label(label),
        _input(attr, placeholder, **kw),
        class_name="w-full",
    )


# ── Dynamic rdata fields per record type ─────────────────────────────

def _fields_a() -> rx.Component:
    return rx.el.div(
        _field("IPv4 Address", "ip_address", "192.168.1.1"),
        class_name="grid grid-cols-1 gap-4",
    )


def _fields_aaaa() -> rx.Component:
    return rx.el.div(
        _field("IPv6 Address", "ip_address", "2001:db8::1"),
        class_name="grid grid-cols-1 gap-4",
    )


def _fields_cname() -> rx.Component:
    return rx.el.div(
        _field("Target Hostname", "hostname", "www.example.com"),
        class_name="grid grid-cols-1 gap-4",
    )


def _fields_mx() -> rx.Component:
    return rx.el.div(
        _field("Priority", "mx_priority", "10"),
        _field("Mail Server", "mx_server", "mail.example.com"),
        class_name="grid grid-cols-2 gap-4",
    )


def _fields_txt() -> rx.Component:
    return rx.el.div(
        _field("Text Value", "txt_value", "v=spf1 +a ~all"),
        class_name="grid grid-cols-1 gap-4",
    )


def _fields_ns() -> rx.Component:
    return rx.el.div(
        _field("Nameserver Hostname", "hostname", "ns1.example.com"),
        class_name="grid grid-cols-1 gap-4",
    )


def _fields_srv() -> rx.Component:
    return rx.el.div(
        _field("Priority", "srv_priority", "10"),
        _field("Weight", "srv_weight", "60"),
        _field("Port", "srv_port", "5060"),
        _field("Target", "srv_target", "sip.example.com"),
        class_name="grid grid-cols-2 md:grid-cols-4 gap-4",
    )


def _fields_ptr() -> rx.Component:
    return rx.el.div(
        _field("Pointer Hostname", "hostname", "host.example.com"),
        class_name="grid grid-cols-1 gap-4",
    )


def _fields_caa() -> rx.Component:
    return rx.el.div(
        _field("Flag", "caa_flag", "0"),
        rx.el.div(
            _label("Tag"),
            rx.el.select(
                rx.el.option("issue", value="issue"),
                rx.el.option("issuewild", value="issuewild"),
                rx.el.option("iodef", value="iodef"),
                on_change=AdvancedDNSState.set_caa_tag,
                value=AdvancedDNSState.caa_tag,
                class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl "
                           "focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none "
                           "transition-all cursor-pointer",
            ),
            class_name="w-full",
        ),
        _field("Value", "caa_value", "letsencrypt.org"),
        class_name="grid grid-cols-3 gap-4",
    )


def _rdata_section() -> rx.Component:
    """Switch form fields based on the selected record type."""
    return rx.match(
        AdvancedDNSState.record_type,
        ("A", _fields_a()),
        ("AAAA", _fields_aaaa()),
        ("CNAME", _fields_cname()),
        ("MX", _fields_mx()),
        ("TXT", _fields_txt()),
        ("NS", _fields_ns()),
        ("SRV", _fields_srv()),
        ("PTR", _fields_ptr()),
        ("CAA", _fields_caa()),
        _fields_a(),
    )


# ── Result banner ────────────────────────────────────────────────────

def _result_banner() -> rx.Component:
    return rx.cond(
        AdvancedDNSState.result_message,
        rx.el.div(
            rx.el.div(
                rx.icon(
                    rx.cond(AdvancedDNSState.result_ok, "check-circle-2", "x-circle"),
                    class_name=rx.cond(
                        AdvancedDNSState.result_ok,
                        "h-5 w-5 text-green-600",
                        "h-5 w-5 text-red-600",
                    ),
                ),
                rx.el.span(
                    AdvancedDNSState.result_message,
                    class_name=rx.cond(
                        AdvancedDNSState.result_ok,
                        "text-sm font-medium text-green-800",
                        "text-sm font-medium text-red-800",
                    ),
                ),
                class_name="flex items-center gap-2",
            ),
            class_name=rx.cond(
                AdvancedDNSState.result_ok,
                "px-4 py-3 bg-green-50 border border-green-200 rounded-xl mb-6",
                "px-4 py-3 bg-red-50 border border-red-200 rounded-xl mb-6",
            ),
        ),
    )


# ── Update history ───────────────────────────────────────────────────

def _history_row(item: dict) -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.span(
                item["type"],
                class_name="px-2 py-0.5 text-xs font-bold rounded bg-blue-100 text-blue-700",
            ),
            class_name="px-4 py-2",
        ),
        rx.el.td(item["name"], class_name="px-4 py-2 text-sm text-gray-700 font-mono"),
        rx.el.td(item["rdata"], class_name="px-4 py-2 text-sm text-gray-600 font-mono"),
        rx.el.td(item["ttl"], class_name="px-4 py-2 text-sm text-gray-500"),
        rx.el.td(
            rx.el.span(
                item["status"],
                class_name=rx.cond(
                    item["status"] == "success",
                    "px-2 py-0.5 text-xs font-bold rounded bg-green-100 text-green-700",
                    "px-2 py-0.5 text-xs font-bold rounded bg-red-100 text-red-700",
                ),
            ),
            class_name="px-4 py-2",
        ),
        class_name="border-b border-gray-100",
    )


def _history_table() -> rx.Component:
    return rx.cond(
        AdvancedDNSState.history.length() > 0,
        rx.el.div(
            rx.el.h3(
                "Session History",
                class_name="text-lg font-bold text-gray-900 mb-4 mt-8",
            ),
            rx.el.div(
                rx.el.table(
                    rx.el.thead(
                        rx.el.tr(
                            rx.el.th("Type", class_name="px-4 py-2 text-left text-xs font-bold uppercase text-gray-400"),
                            rx.el.th("Name", class_name="px-4 py-2 text-left text-xs font-bold uppercase text-gray-400"),
                            rx.el.th("RData", class_name="px-4 py-2 text-left text-xs font-bold uppercase text-gray-400"),
                            rx.el.th("TTL", class_name="px-4 py-2 text-left text-xs font-bold uppercase text-gray-400"),
                            rx.el.th("Status", class_name="px-4 py-2 text-left text-xs font-bold uppercase text-gray-400"),
                        ),
                    ),
                    rx.el.tbody(
                        rx.foreach(AdvancedDNSState.history, _history_row),
                    ),
                    class_name="w-full",
                ),
                class_name="bg-white rounded-2xl border border-gray-100 overflow-hidden",
            ),
        ),
    )


# ── Main view ────────────────────────────────────────────────────────

def advanced_dns_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            # ── Header ──
            rx.el.div(
                rx.el.h2(
                    "Advanced DNS Update",
                    class_name="text-xl font-bold text-gray-900",
                ),
                rx.el.p(
                    "Execute RFC 2136 dynamic DNS updates against any BIND9 server.",
                    class_name="text-sm text-gray-500",
                ),
                class_name="mb-6",
            ),

            _result_banner(),

            # ── Server & TSIG section ──
            rx.el.div(
                rx.el.div(
                    _field("Nameserver IP", "server_ip", "127.0.0.1"),
                    _field("Zone Name", "zone_name", "reflex-ddns.com"),
                    class_name="grid grid-cols-1 md:grid-cols-2 gap-6",
                ),

                rx.el.div(
                    _field("TSIG Key Name", "key_name", "tsig-key"),
                    rx.el.div(
                        _label("TSIG Secret"),
                        rx.el.div(
                            rx.el.input(
                                value=AdvancedDNSState.key_secret,
                                on_change=AdvancedDNSState.set_key_secret,
                                type=rx.cond(AdvancedDNSState.show_secret, "text", "password"),
                                placeholder="Base64 TSIG secret…",
                                class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl "
                                           "focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none "
                                           "transition-all hover:border-gray-300 pr-10",
                            ),
                            rx.el.button(
                                rx.icon(
                                    rx.cond(AdvancedDNSState.show_secret, "eye-off", "eye"),
                                    class_name="h-4 w-4",
                                ),
                                type="button",
                                on_click=AdvancedDNSState.toggle_secret_visibility,
                                class_name="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600",
                            ),
                            class_name="relative",
                        ),
                        class_name="w-full",
                    ),
                    rx.el.div(
                        rx.el.button(
                            rx.icon("refresh-cw", class_name="h-3.5 w-3.5"),
                            "Reload TSIG from env",
                            on_click=AdvancedDNSState.reload_tsig,
                            type="button",
                            class_name="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-800 font-medium mt-1",
                        ),
                        class_name="flex items-end",
                    ),
                    class_name="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6",
                ),
                class_name="pb-6 border-b border-gray-200",
            ),

            # ── Record section ──
            rx.el.div(
                rx.el.h3(
                    "Record Details",
                    class_name="text-lg font-bold text-gray-900 mb-4 mt-6",
                ),

                rx.el.div(
                    _field("Record Name", "record_name", "subdomain"),
                    rx.el.div(
                        _label("Record Type"),
                        rx.el.div(
                            rx.el.select(
                                *[
                                    rx.el.option(label, value=val)
                                    for val, label in _TYPE_OPTIONS
                                ],
                                on_change=AdvancedDNSState.set_record_type,
                                value=AdvancedDNSState.record_type,
                                class_name="w-full appearance-none px-4 py-2.5 bg-gray-50 border border-gray-200 "
                                           "rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 "
                                           "outline-none transition-all cursor-pointer",
                            ),
                            rx.icon(
                                "chevron-down",
                                class_name="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none",
                            ),
                            class_name="relative",
                        ),
                        class_name="w-full",
                    ),
                    _field("TTL", "ttl", "300"),
                    class_name="grid grid-cols-1 md:grid-cols-3 gap-6",
                ),

                # ── Type-specific rdata fields ──
                rx.el.div(
                    rx.el.label(
                        "Record Data",
                        class_name="block text-sm font-bold text-gray-600 mb-2",
                    ),
                    _rdata_section(),
                    class_name="mt-6 p-4 bg-blue-50/50 border border-blue-100 rounded-2xl",
                ),

                # ── Execute button ──
                rx.el.div(
                    rx.el.button(
                        rx.cond(
                            AdvancedDNSState.is_updating,
                            rx.el.div(
                                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                                "Updating…",
                                class_name="flex items-center gap-2",
                            ),
                            rx.el.div(
                                rx.icon("zap", class_name="h-4 w-4"),
                                "Execute DNS Update",
                                class_name="flex items-center gap-2",
                            ),
                        ),
                        on_click=AdvancedDNSState.execute_update,
                        disabled=AdvancedDNSState.is_updating,
                        class_name="px-8 py-3 bg-blue-600 text-white font-bold rounded-xl "
                                   "hover:bg-blue-700 shadow-lg shadow-blue-200 transition-all "
                                   "active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed",
                    ),
                    class_name="mt-8 flex justify-end",
                ),
                class_name="mt-2",
            ),

            class_name="bg-white p-8 rounded-3xl border border-gray-100 shadow-sm",
        ),

        # ── History table ──
        _history_table(),

        class_name="max-w-4xl mx-auto py-8",
    )
