"""DNS Records page – shows registered services + manual DNS records."""

import reflex as rx
from re_ddns.states.dns_records_state import (
    DNSRecordsState,
    ServiceEntry,
    ManualDNSEntry,
)


def _service_row(svc: ServiceEntry) -> rx.Component:
    """One row in the auto-registered services table."""
    return rx.el.tr(
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
            rx.el.button(
                rx.icon("trash-2", class_name="h-4 w-4"),
                on_click=DNSRecordsState.delete_service(svc["subdomain"]),
                class_name="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors",
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-50 hover:bg-gray-50 transition-colors",
    )


def _manual_row(rec: ManualDNSEntry) -> rx.Component:
    """One row in the manual DNS records table."""
    return rx.el.tr(
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
            rx.el.button(
                rx.icon("trash-2", class_name="h-4 w-4"),
                on_click=DNSRecordsState.delete_manual_record(rec["subdomain"]),
                class_name="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors",
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-50 hover:bg-gray-50 transition-colors",
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
            "Point a subdomain to any IP address (e.g. external server, NAS).",
            class_name="text-sm text-gray-500 mb-2",
        ),
        rx.el.div(
            rx.icon("info", class_name="h-4 w-4 text-amber-500 mt-0.5 shrink-0"),
            rx.el.p(
                "CNAME records only work from outside Docker (e.g. Mac browser with DNS set to 127.0.0.1). "
                "Apps inside Docker should access external sites by their real domain directly.",
                class_name="text-xs text-amber-700",
            ),
            class_name="flex gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl mb-4",
        ),
        rx.el.div(
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
            rx.el.div(
                rx.el.label(
                    "IP Address",
                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                ),
                rx.el.input(
                    placeholder="203.0.113.5",
                    value=DNSRecordsState.manual_ip,
                    on_change=DNSRecordsState.set_manual_ip,
                    class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all hover:border-gray-300",
                ),
                class_name="flex-1",
            ),
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
