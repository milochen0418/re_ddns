import reflex as rx
from re_ddns.components.sidebar import sidebar
from re_ddns.components.config_form import config_panel, config_summary_card
from re_ddns.states.ui import UIState
from re_ddns.states.config import ConfigState
from re_ddns.states.ip_state import IPState
from re_ddns.states.dns_update_state import DNSUpdateState
from re_ddns.states.activity_log_state import ActivityLogState, LogEntry


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.el.button(
                rx.icon("menu", class_name="h-6 w-6"),
                on_click=UIState.toggle_sidebar,
                class_name="md:hidden p-2 text-gray-600 hover:bg-gray-100 rounded-lg",
            ),
            rx.el.h2(
                UIState.current_page, class_name="text-xl font-bold text-gray-800"
            ),
            class_name="flex items-center gap-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.span("Client ID: ", class_name="text-gray-400"),
                rx.el.span("DDNS-NODE-01", class_name="text-gray-700 font-bold"),
                class_name="text-sm px-4 py-2 bg-gray-50 rounded-full hidden sm:block",
            ),
            class_name="flex items-center gap-4",
        ),
        class_name="h-16 border-b border-gray-100 bg-white/80 backdrop-blur-md flex items-center justify-between px-8 sticky top-0 z-30",
    )


def dashboard_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h3(
                    "System Status", class_name="text-2xl font-bold text-gray-900"
                ),
                rx.el.div(
                    rx.el.button(
                        rx.cond(
                            IPState.is_loading,
                            rx.icon("squirrel", class_name="h-4 w-4 animate-spin"),
                            rx.icon("refresh-cw", class_name="h-4 w-4"),
                        ),
                        "Check Now",
                        on_click=IPState.detect_ip,
                        disabled=IPState.is_loading,
                        class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 hover:border-gray-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed",
                    ),
                    rx.el.button(
                        rx.cond(
                            IPState.is_monitoring,
                            rx.el.div(
                                rx.icon("pause", class_name="h-4 w-4"),
                                "Monitoring On",
                                class_name="flex items-center gap-2",
                            ),
                            rx.el.div(
                                rx.icon("play", class_name="h-4 w-4"),
                                "Monitoring Off",
                                class_name="flex items-center gap-2",
                            ),
                        ),
                        on_click=IPState.toggle_monitoring,
                        class_name=rx.cond(
                            IPState.is_monitoring,
                            "px-4 py-2 bg-green-100 text-green-700 font-medium rounded-xl border border-green-200 hover:bg-green-200 transition-all",
                            "px-4 py-2 bg-gray-100 text-gray-700 font-medium rounded-xl border border-gray-200 hover:bg-gray-200 transition-all",
                        ),
                    ),
                    class_name="flex items-center gap-3",
                ),
                class_name="flex items-center justify-between mb-6",
            ),
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.el.div(
                            rx.icon("globe", class_name="h-6 w-6 text-blue-600"),
                            class_name="p-3 bg-blue-100 rounded-2xl",
                        ),
                        rx.el.div(
                            rx.el.p(
                                "Current External IP",
                                class_name="text-sm font-medium text-gray-500",
                            ),
                            rx.cond(
                                IPState.is_loading,
                                rx.el.div(
                                    class_name="h-8 w-32 bg-gray-200 rounded animate-pulse mt-1"
                                ),
                                rx.el.p(
                                    IPState.current_ip,
                                    class_name=rx.cond(
                                        IPState.ip_changed,
                                        "text-2xl font-black text-orange-500",
                                        "text-2xl font-black text-gray-900",
                                    ),
                                ),
                            ),
                            rx.cond(
                                IPState.ip_changed,
                                rx.el.div(
                                    rx.icon("wheat", class_name="h-3 w-3 mr-1"),
                                    "IP Changed",
                                    class_name="flex items-center text-xs font-bold text-orange-500 mt-2 bg-orange-50 px-2 py-1 rounded-full w-fit",
                                ),
                                rx.el.div(
                                    rx.icon("languages", class_name="h-3 w-3 mr-1"),
                                    "Stable",
                                    class_name="flex items-center text-xs font-bold text-green-600 mt-2 bg-green-50 px-2 py-1 rounded-full w-fit",
                                ),
                            ),
                            class_name="mt-4",
                        ),
                        class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm relative overflow-hidden",
                    ),
                    rx.el.div(
                        rx.el.div(
                            rx.icon("clock", class_name="h-6 w-6 text-purple-600"),
                            class_name="p-3 bg-purple-100 rounded-2xl",
                        ),
                        rx.el.div(
                            rx.el.p(
                                "Last Checked",
                                class_name="text-sm font-medium text-gray-500",
                            ),
                            rx.el.p(
                                IPState.last_checked,
                                class_name="text-2xl font-black text-gray-900",
                            ),
                            rx.el.div(
                                rx.el.span("Previous: ", class_name="font-medium"),
                                rx.cond(
                                    IPState.previous_ip, IPState.previous_ip, "None"
                                ),
                                class_name="text-xs text-gray-400 mt-2",
                            ),
                            class_name="mt-4",
                        ),
                        class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm",
                    ),
                    rx.el.div(
                        rx.el.div(
                            rx.icon("timer", class_name="h-6 w-6 text-green-600"),
                            class_name="p-3 bg-green-100 rounded-2xl",
                        ),
                        rx.el.div(
                            rx.el.p(
                                "Check Interval",
                                class_name="text-sm font-medium text-gray-500",
                            ),
                            rx.el.p(
                                f"{IPState.check_interval}s",
                                class_name="text-2xl font-black text-gray-900",
                            ),
                            rx.cond(
                                IPState.is_monitoring,
                                rx.el.div(
                                    rx.el.span(class_name="relative flex h-2 w-2 mr-2"),
                                    rx.el.span(
                                        class_name="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-green-400 opacity-75"
                                    ),
                                    rx.el.span(
                                        class_name="relative inline-flex rounded-full h-2 w-2 bg-green-500"
                                    ),
                                    "Running",
                                    class_name="flex items-center text-xs font-bold text-green-600 mt-2",
                                ),
                                rx.el.div(
                                    rx.el.span(
                                        class_name="h-2 w-2 rounded-full bg-gray-300 mr-2"
                                    ),
                                    "Paused",
                                    class_name="flex items-center text-xs font-bold text-gray-400 mt-2",
                                ),
                            ),
                            class_name="mt-4",
                        ),
                        class_name="p-6 bg-white rounded-3xl border border-gray-100 shadow-sm",
                    ),
                    class_name="grid grid-cols-1 md:grid-cols-3 gap-6",
                ),
                rx.el.div(
                    rx.el.div(
                        rx.el.div(
                            rx.el.h3(
                                "DNS Update Operations",
                                class_name="text-lg font-bold text-gray-900",
                            ),
                            rx.el.p(
                                "Manually trigger a DNS update or view latest status.",
                                class_name="text-sm text-gray-500",
                            ),
                            class_name="mb-4",
                        ),
                        rx.el.button(
                            rx.cond(
                                DNSUpdateState.is_updating,
                                rx.el.div(
                                    rx.icon(
                                        "squirrel",
                                        class_name="h-5 w-5 animate-spin mr-2",
                                    ),
                                    "Updating DNS...",
                                    class_name="flex items-center",
                                ),
                                rx.el.div(
                                    rx.icon("cloud-upload", class_name="h-5 w-5 mr-2"),
                                    "Force Update DNS",
                                    class_name="flex items-center",
                                ),
                            ),
                            on_click=DNSUpdateState.update_dns,
                            disabled=DNSUpdateState.is_updating,
                            class_name="px-6 py-3 bg-blue-600 text-white font-bold rounded-xl hover:bg-blue-700 shadow-lg shadow-blue-200 transition-all disabled:opacity-70 disabled:cursor-not-allowed",
                        ),
                        class_name="flex flex-col md:flex-row items-start md:items-center justify-between",
                    ),
                    rx.cond(
                        DNSUpdateState.last_update_message,
                        rx.el.div(
                            rx.icon(
                                rx.cond(
                                    DNSUpdateState.last_update_status == "success",
                                    "check-circle-2",
                                    "alert-circle",
                                ),
                                class_name=rx.cond(
                                    DNSUpdateState.last_update_status == "success",
                                    "h-5 w-5 text-green-600 mr-2",
                                    "h-5 w-5 text-red-600 mr-2",
                                ),
                            ),
                            rx.el.span(
                                DNSUpdateState.last_update_message,
                                class_name="font-medium",
                            ),
                            class_name=rx.cond(
                                DNSUpdateState.last_update_status == "success",
                                "mt-4 p-4 bg-green-50 text-green-800 rounded-xl flex items-center border border-green-100",
                                "mt-4 p-4 bg-red-50 text-red-800 rounded-xl flex items-center border border-red-100",
                            ),
                        ),
                        None,
                    ),
                    class_name="mt-8 p-6 bg-white rounded-3xl border border-gray-100 shadow-sm",
                ),
                class_name="w-full",
            ),
            class_name="py-8",
        ),
        class_name="animate-in fade-in duration-500",
    )


def log_item(entry: LogEntry) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon(
                rx.match(
                    entry["status"],
                    ("success", "check-circle-2"),
                    ("error", "alert-circle"),
                    "info",
                ),
                class_name=rx.match(
                    entry["status"],
                    ("success", "h-5 w-5 text-green-600"),
                    ("error", "h-5 w-5 text-red-600"),
                    "h-5 w-5 text-blue-600",
                ),
            ),
            class_name=rx.match(
                entry["status"],
                ("success", "p-2 bg-green-100 rounded-full shrink-0"),
                ("error", "p-2 bg-red-100 rounded-full shrink-0"),
                "p-2 bg-blue-100 rounded-full shrink-0",
            ),
        ),
        rx.el.div(
            rx.el.div(
                rx.el.p(entry["message"], class_name="font-semibold text-gray-900"),
                rx.el.p(
                    f"IP: {entry['ip_address']}",
                    class_name="text-xs text-gray-500 font-mono mt-1",
                ),
            ),
            rx.el.p(
                entry["timestamp"],
                class_name="text-xs text-gray-400 font-medium whitespace-nowrap",
            ),
            class_name="flex-1 flex justify-between items-start gap-4",
        ),
        class_name="flex items-start gap-4 p-4 border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors",
    )


def activity_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h3(
                    "Recent Activity", class_name="text-2xl font-bold text-gray-900"
                ),
                rx.el.button(
                    rx.icon("trash-2", class_name="h-4 w-4 mr-2"),
                    "Clear Logs",
                    on_click=ActivityLogState.clear_logs,
                    class_name="flex items-center text-sm font-medium text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors",
                ),
                class_name="flex items-center justify-between mb-6",
            ),
            rx.el.div(
                rx.cond(
                    ActivityLogState.logs.length() > 0,
                    rx.el.div(
                        rx.foreach(ActivityLogState.logs, log_item),
                        class_name="flex flex-col",
                    ),
                    rx.el.div(
                        rx.icon(
                            "scroll-text", class_name="h-12 w-12 text-gray-300 mb-4"
                        ),
                        rx.el.p(
                            "No activity recorded yet.",
                            class_name="text-gray-400 font-medium",
                        ),
                        class_name="flex flex-col items-center justify-center h-64 border-2 border-dashed border-gray-100 rounded-3xl",
                    ),
                ),
                class_name="bg-white rounded-3xl shadow-sm border border-gray-100 overflow-hidden",
            ),
            class_name="py-8",
        )
    )


def index() -> rx.Component:
    return rx.el.main(
        rx.el.div(
            sidebar(),
            rx.el.div(
                header(),
                rx.el.div(
                    rx.match(
                        UIState.current_page,
                        ("Dashboard", dashboard_view()),
                        (
                            "Configuration",
                            rx.cond(
                                ConfigState.is_saved,
                                config_summary_card(),
                                config_panel(),
                            ),
                        ),
                        ("Activity Log", activity_view()),
                        dashboard_view(),
                    ),
                    class_name="flex-1 p-8 overflow-y-auto",
                ),
                class_name="flex-1 flex flex-col h-screen overflow-hidden",
            ),
            class_name="flex min-h-screen w-screen bg-gray-50",
        ),
        class_name="font-['Inter']",
    )


app = rx.App(
    theme=rx.theme(appearance="light"),
    head_components=[
        rx.el.link(rel="preconnect", href="https://fonts.googleapis.com"),
        rx.el.link(rel="preconnect", href="https://fonts.gstatic.com", cross_origin=""),
        rx.el.link(
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap",
            rel="stylesheet",
        ),
    ],
)
app.add_page(index, route="/", on_load=[IPState.detect_ip, IPState.toggle_monitoring])