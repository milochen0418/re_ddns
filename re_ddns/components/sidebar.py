import reflex as rx
from re_ddns.states.ui import UIState


def nav_item(label: str, icon: str) -> rx.Component:
    is_active = UIState.current_page == label
    return rx.el.button(
        rx.icon(icon, class_name="h-5 w-5"),
        rx.el.span(label, class_name="font-medium"),
        on_click=lambda: UIState.set_page(label),
        class_name=rx.cond(
            is_active,
            "flex items-center gap-3 w-full px-4 py-3 bg-blue-600 text-white rounded-xl transition-all shadow-md",
            "flex items-center gap-3 w-full px-4 py-3 text-gray-400 hover:text-white hover:bg-gray-800 rounded-xl transition-all",
        ),
    )


def sidebar() -> rx.Component:
    return rx.el.aside(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("shield-check", class_name="h-8 w-8 text-blue-500"),
                    rx.el.h1(
                        "BIND9 DDNS",
                        class_name="text-xl font-bold tracking-tight text-white",
                    ),
                    class_name="flex items-center gap-3",
                ),
                class_name="px-6 py-8 mb-4",
            ),
            rx.el.nav(
                nav_item("Dashboard", "layout-dashboard"),
                nav_item("Configuration", "settings"),
                nav_item("Activity Log", "list-tree"),
                class_name="px-4 space-y-2",
            ),
            class_name="flex-1",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.div(class_name="h-2 w-2 rounded-full bg-green-500 animate-pulse"),
                rx.el.span(
                    "Service: Active", class_name="text-xs text-gray-400 font-medium"
                ),
                class_name="flex items-center gap-2 px-6 py-6 border-t border-gray-800",
            ),
            class_name="mt-auto",
        ),
        class_name="hidden md:flex flex-col w-72 bg-gray-950 h-screen sticky top-0 border-r border-gray-800 shadow-2xl",
    )