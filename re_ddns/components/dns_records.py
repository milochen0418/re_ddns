"""DNS Records page – shows registered services + manual DNS records."""

import reflex as rx
from re_ddns.states.dns_records_state import (
    DNSRecordsState,
    ServiceEntry,
    ManualDNSEntry,
)


def _debug_code_block(label: str, content: rx.Var[str]) -> rx.Component:
    """A labelled code block for the debug detail panel."""
    return rx.el.div(
        rx.el.p(label, class_name="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1"),
        rx.el.pre(
            content,
            class_name="text-xs font-mono text-gray-700 bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto",
        ),
    )


def _detail_panel(subdomain: rx.Var[str], col_span: int) -> rx.Component:
    """Expandable detail row showing nginx, JSON, and BIND9 info."""
    return rx.cond(
        DNSRecordsState.expanded_subdomain == subdomain,
        rx.el.tr(
            rx.el.td(
                rx.cond(
                    DNSRecordsState.detail_loading,
                    rx.el.div(
                        rx.icon("loader-circle", class_name="h-5 w-5 animate-spin text-gray-400"),
                        rx.el.span("Loading debug info…", class_name="text-sm text-gray-400"),
                        class_name="flex items-center gap-2 py-4",
                    ),
                    rx.el.div(
                        _debug_code_block("BIND9 DNS Records (dig @127.0.0.1)", DNSRecordsState.detail_bind9_dig),
                        _debug_code_block("registry.json", DNSRecordsState.detail_registry_json),
                        _debug_code_block("manual_dns.json", DNSRecordsState.detail_manual_json),
                        _debug_code_block("nginx config", DNSRecordsState.detail_nginx_conf),
                        class_name="grid grid-cols-1 md:grid-cols-2 gap-3 p-4",
                    ),
                ),
                col_span=col_span,
                class_name="bg-slate-50 border-b border-gray-200",
            ),
        ),
    )


def _service_row(svc: ServiceEntry) -> rx.Component:
    """One row in the auto-registered services table + expandable detail."""
    return rx.fragment(
        rx.el.tr(
            rx.el.td(
                rx.el.span(
                    svc["subdomain"],
                    class_name="font-semibold text-gray-900",
                ),
                rx.el.span(
                    f".{svc['zone']}",
                    class_name="text-gray-400",
                ),
                class_name="px-4 py-3",
            ),
            rx.el.td(
                svc["upstream_host"],
                class_name="px-4 py-3 text-gray-600 font-mono text-sm",
            ),
            rx.el.td(
                f"{svc['frontend_port']}/{svc['backend_port']}",
                class_name="px-4 py-3 text-gray-600 text-sm",
            ),
            rx.el.td(
                svc["ip_address"],
                class_name="px-4 py-3 text-gray-600 font-mono text-sm",
            ),
            rx.el.td(
                rx.el.span(
                    "Auto",
                    class_name="px-2 py-0.5 bg-blue-50 text-blue-600 text-xs font-semibold rounded-full",
                ),
                class_name="px-4 py-3",
            ),
            rx.el.td(
                rx.el.div(
                    rx.el.button(
                        rx.icon("search", class_name="h-4 w-4"),
                        on_click=DNSRecordsState.toggle_row_detail(svc["subdomain"]),
                        title="Inspect",
                        class_name="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors",
                    ),
                    rx.el.button(
                        rx.icon("trash-2", class_name="h-4 w-4"),
                        on_click=DNSRecordsState.delete_service(svc["subdomain"]),
                        class_name="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors",
                    ),
                    class_name="flex gap-1",
                ),
                class_name="px-4 py-3",
            ),
            class_name="border-b border-gray-50 hover:bg-gray-50 transition-colors cursor-pointer",
            on_click=DNSRecordsState.toggle_row_detail(svc["subdomain"]),
        ),
        _detail_panel(svc["subdomain"], 6),
    )


def _manual_row(rec: ManualDNSEntry) -> rx.Component:
    """One row in the manual DNS records table + expandable detail."""
    return rx.fragment(
        rx.el.tr(
            rx.el.td(
                rx.el.span(
                    rec["subdomain"],
                    class_name="font-semibold text-gray-900",
                ),
                rx.el.span(
                    f".{rec['zone']}",
                    class_name="text-gray-400",
                ),
                class_name="px-4 py-3",
            ),
            rx.el.td(
                rec["ip_address"],
                class_name="px-4 py-3 text-gray-600 font-mono text-sm",
            ),
            rx.el.td(
                rec["record_type"],
                class_name="px-4 py-3 text-gray-600 text-sm",
            ),
            rx.el.td(
                f"{rec['ttl']}s",
                class_name="px-4 py-3 text-gray-600 text-sm",
            ),
            rx.el.td(
                rx.el.span(
                    "Manual",
                    class_name="px-2 py-0.5 bg-orange-50 text-orange-600 text-xs font-semibold rounded-full",
                ),
                class_name="px-4 py-3",
            ),
            rx.el.td(
                rx.el.div(
                    rx.el.button(
                        rx.icon("search", class_name="h-4 w-4"),
                        on_click=DNSRecordsState.toggle_row_detail(rec["subdomain"]),
                        title="Inspect",
                        class_name="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors",
                    ),
                    rx.el.button(
                        rx.icon("trash-2", class_name="h-4 w-4"),
                        on_click=DNSRecordsState.delete_manual_record(rec["subdomain"]),
                        class_name="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors",
                    ),
                    class_name="flex gap-1",
                ),
                class_name="px-4 py-3",
            ),
            class_name="border-b border-gray-50 hover:bg-gray-50 transition-colors cursor-pointer",
            on_click=DNSRecordsState.toggle_row_detail(rec["subdomain"]),
        ),
        _detail_panel(rec["subdomain"], 6),
    )


def _table_header(*cols: str) -> rx.Component:
    return rx.el.thead(
        rx.el.tr(
            *[
                rx.el.th(
                    c,
                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                )
                for c in cols
            ],
            class_name="bg-gray-50/80",
        )
    )


def _add_manual_form() -> rx.Component:
    """Inline form to add a manual DNS record."""
    return rx.el.div(
        rx.el.h4(
            "Add Manual DNS Record",
            class_name="text-lg font-bold text-gray-900 mb-4",
        ),
        rx.el.p(
            "Point a subdomain to any IP address, hostname, or other DNS target.",
            class_name="text-sm text-gray-500 mb-4",
        ),
        # Record type hint banner — dynamically shown for each type
        rx.el.div(
            rx.icon("info", class_name="h-4 w-4 text-amber-500 mt-0.5 shrink-0"),
            rx.el.p(
                rx.cond(
                    DNSRecordsState.manual_record_type == "A",
                    "A — Maps domain to an IPv4 address. Works both inside Docker and externally.",
                    rx.cond(
                        DNSRecordsState.manual_record_type == "AAAA",
                        "AAAA — Maps domain to an IPv6 address. Works both inside Docker and externally.",
                        rx.cond(
                            DNSRecordsState.manual_record_type == "CNAME",
                            "CNAME — Alias to another domain. External only (e.g. Mac browser with DNS → 127.0.0.1). "
                            "Apps inside Docker should access external sites by their real domain directly.",
                            rx.cond(
                                DNSRecordsState.manual_record_type == "MX",
                                "MX — Specifies mail server for the domain. External only — no mail service runs inside Docker.",
                                rx.cond(
                                    DNSRecordsState.manual_record_type == "TXT",
                                    "TXT — Stores arbitrary text (SPF, DKIM, domain verification). Works both inside Docker and externally.",
                                    rx.cond(
                                        DNSRecordsState.manual_record_type == "NS",
                                        "NS — Delegates a subdomain to another nameserver. External only — Docker embedded DNS won't follow delegation.",
                                        "PTR — Reverse DNS lookup (IP → domain). Requires a reverse zone (in-addr.arpa) which is not configured here.",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                class_name="text-xs text-amber-700",
            ),
            class_name="flex gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl mb-4",
        ),
        rx.el.div(
            # Record Type selector
            rx.el.div(
                rx.el.label(
                    "Type",
                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                ),
                rx.el.select(
                    rx.el.option("A", value="A"),
                    rx.el.option("AAAA", value="AAAA"),
                    rx.el.option("CNAME", value="CNAME"),
                    rx.el.option("MX", value="MX"),
                    rx.el.option("TXT", value="TXT"),
                    rx.el.option("NS", value="NS"),
                    rx.el.option("PTR", value="PTR"),
                    value=DNSRecordsState.manual_record_type,
                    on_change=DNSRecordsState.set_manual_record_type,
                    class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all cursor-pointer",
                ),
                class_name="w-32",
            ),
            # Subdomain
            rx.el.div(
                rx.el.label(
                    "Subdomain",
                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                ),
                rx.el.div(
                    rx.el.input(
                        placeholder="blog",
                        value=DNSRecordsState.manual_subdomain,
                        on_change=DNSRecordsState.set_manual_subdomain,
                        class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-l-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all hover:border-gray-300",
                    ),
                    rx.el.span(
                        ".reflex-ddns.com",
                        class_name="px-3 py-2.5 bg-gray-100 border border-l-0 border-gray-200 rounded-r-xl text-sm text-gray-500 whitespace-nowrap",
                    ),
                    class_name="flex",
                ),
                class_name="flex-1",
            ),
            # Value — label and placeholder change based on record type
            rx.el.div(
                rx.el.label(
                    rx.cond(
                        DNSRecordsState.manual_record_type == "CNAME",
                        "Target Hostname",
                        rx.cond(
                            DNSRecordsState.manual_record_type == "AAAA",
                            "IPv6 Address",
                            rx.cond(
                                DNSRecordsState.manual_record_type == "MX",
                                "Mail Server (priority host)",
                                rx.cond(
                                    DNSRecordsState.manual_record_type == "TXT",
                                    "Text Value",
                                    rx.cond(
                                        DNSRecordsState.manual_record_type == "NS",
                                        "Nameserver",
                                        rx.cond(
                                            DNSRecordsState.manual_record_type == "PTR",
                                            "Pointer Hostname",
                                            "IPv4 Address",
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                ),
                rx.el.input(
                    placeholder=rx.cond(
                        DNSRecordsState.manual_record_type == "CNAME",
                        "www.example.com",
                        rx.cond(
                            DNSRecordsState.manual_record_type == "AAAA",
                            "2001:db8::1",
                            rx.cond(
                                DNSRecordsState.manual_record_type == "MX",
                                "10 mail.example.com",
                                rx.cond(
                                    DNSRecordsState.manual_record_type == "TXT",
                                    "v=spf1 +a ~all",
                                    rx.cond(
                                        DNSRecordsState.manual_record_type == "NS",
                                        "ns1.example.com",
                                        rx.cond(
                                            DNSRecordsState.manual_record_type == "PTR",
                                            "host.example.com",
                                            "203.0.113.5",
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    value=DNSRecordsState.manual_ip,
                    on_change=DNSRecordsState.set_manual_ip,
                    class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all hover:border-gray-300",
                ),
                class_name="flex-1",
            ),
            # TTL
            rx.el.div(
                rx.el.label(
                    "TTL (s)",
                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                ),
                rx.el.input(
                    placeholder="300",
                    value=DNSRecordsState.manual_ttl,
                    on_change=DNSRecordsState.set_manual_ttl,
                    class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all hover:border-gray-300",
                ),
                class_name="w-28",
            ),
            # Add button
            rx.el.div(
                rx.el.label(
                    "\u00a0",  # non-breaking space for alignment
                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                ),
                rx.el.button(
                    rx.icon("plus", class_name="h-4 w-4 mr-1"),
                    "Add",
                    on_click=DNSRecordsState.add_manual_record,
                    disabled=DNSRecordsState.is_loading,
                    class_name="flex items-center px-5 py-2.5 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 shadow-sm transition-all disabled:opacity-50",
                ),
                class_name="w-auto",
            ),
            class_name="flex gap-4 items-end flex-wrap",
        ),
        class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm",
    )


def dns_records_view() -> rx.Component:
    """Full DNS Records page."""
    return rx.el.div(
        rx.el.div(
            # ── Header ──
            rx.el.div(
                rx.el.h3(
                    "DNS Records",
                    class_name="text-2xl font-bold text-gray-900",
                ),
                rx.el.button(
                    rx.cond(
                        DNSRecordsState.is_loading,
                        rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                        rx.icon("refresh-cw", class_name="h-4 w-4"),
                    ),
                    "Refresh",
                    on_click=DNSRecordsState.load_records,
                    disabled=DNSRecordsState.is_loading,
                    class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all disabled:opacity-50",
                ),
                class_name="flex items-center justify-between mb-6",
            ),
            # ── Feedback message ──
            rx.cond(
                DNSRecordsState.feedback_message,
                rx.el.div(
                    rx.icon(
                        rx.cond(
                            DNSRecordsState.feedback_ok,
                            "check-circle-2",
                            "alert-circle",
                        ),
                        class_name=rx.cond(
                            DNSRecordsState.feedback_ok,
                            "h-5 w-5 text-green-600 mr-2 shrink-0",
                            "h-5 w-5 text-red-600 mr-2 shrink-0",
                        ),
                    ),
                    rx.el.span(
                        DNSRecordsState.feedback_message,
                        class_name="font-medium",
                    ),
                    class_name=rx.cond(
                        DNSRecordsState.feedback_ok,
                        "mb-6 p-4 bg-green-50 text-green-800 rounded-xl flex items-center border border-green-100",
                        "mb-6 p-4 bg-red-50 text-red-800 rounded-xl flex items-center border border-red-100",
                    ),
                ),
                None,
            ),
            # ── Auto-registered services ──
            rx.el.div(
                rx.el.div(
                    rx.icon("server", class_name="h-5 w-5 text-blue-600"),
                    rx.el.h4(
                        "Registered Services",
                        class_name="text-lg font-bold text-gray-900",
                    ),
                    rx.el.span(
                        DNSRecordsState.services.length(),
                        class_name="px-2 py-0.5 bg-blue-50 text-blue-600 text-xs font-semibold rounded-full",
                    ),
                    class_name="flex items-center gap-2 mb-4",
                ),
                rx.el.p(
                    "Services auto-registered by containers (DNS + nginx + TLS).",
                    class_name="text-sm text-gray-500 mb-4",
                ),
                rx.cond(
                    DNSRecordsState.services.length() > 0,
                    rx.el.div(
                        rx.el.table(
                            _table_header(
                                "Domain", "Upstream", "Ports", "DNS IP", "Type", "",
                            ),
                            rx.el.tbody(
                                rx.foreach(DNSRecordsState.services, _service_row),
                            ),
                            class_name="w-full",
                        ),
                        class_name="overflow-x-auto rounded-2xl border border-gray-100",
                    ),
                    rx.el.div(
                        rx.icon("inbox", class_name="h-10 w-10 text-gray-300 mb-2"),
                        rx.el.p(
                            "No services registered yet.",
                            class_name="text-gray-400 font-medium",
                        ),
                        class_name="flex flex-col items-center justify-center h-32 border-2 border-dashed border-gray-100 rounded-2xl",
                    ),
                ),
                class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm mb-6",
            ),
            # ── Manual DNS records ──
            rx.el.div(
                rx.el.div(
                    rx.icon("globe", class_name="h-5 w-5 text-orange-600"),
                    rx.el.h4(
                        "Manual DNS Records",
                        class_name="text-lg font-bold text-gray-900",
                    ),
                    rx.el.span(
                        DNSRecordsState.manual_records.length(),
                        class_name="px-2 py-0.5 bg-orange-50 text-orange-600 text-xs font-semibold rounded-full",
                    ),
                    class_name="flex items-center gap-2 mb-4",
                ),
                rx.el.p(
                    "Custom DNS records pointing to any IP (no reverse proxy).",
                    class_name="text-sm text-gray-500 mb-4",
                ),
                rx.cond(
                    DNSRecordsState.manual_records.length() > 0,
                    rx.el.div(
                        rx.el.table(
                            _table_header(
                                "Domain", "IP Address", "Type", "TTL", "Source", "",
                            ),
                            rx.el.tbody(
                                rx.foreach(
                                    DNSRecordsState.manual_records, _manual_row
                                ),
                            ),
                            class_name="w-full",
                        ),
                        class_name="overflow-x-auto rounded-2xl border border-gray-100",
                    ),
                    rx.el.div(
                        rx.icon("inbox", class_name="h-10 w-10 text-gray-300 mb-2"),
                        rx.el.p(
                            "No manual DNS records yet.",
                            class_name="text-gray-400 font-medium",
                        ),
                        class_name="flex flex-col items-center justify-center h-32 border-2 border-dashed border-gray-100 rounded-2xl",
                    ),
                ),
                class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm mb-6",
            ),
            # ── Add Manual Record form ──
            _add_manual_form(),
            class_name="py-8",
        ),
        class_name="animate-in fade-in duration-500",
    )
