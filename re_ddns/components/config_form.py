import reflex as rx
from re_ddns.states.config import ConfigState


def form_field(
    label: str, name: str, placeholder: str, type: str = "text", help_text: str = ""
) -> rx.Component:
    error_msg = ConfigState.errors.get(name)
    return rx.el.div(
        rx.el.label(
            label, class_name="block text-sm font-semibold text-gray-700 mb-1.5"
        ),
        rx.el.input(
            name=name,
            type=type,
            placeholder=placeholder,
            default_value=getattr(ConfigState, name),
            class_name=rx.cond(
                error_msg,
                "w-full px-4 py-2.5 bg-white border-2 border-red-500 rounded-xl focus:ring-4 focus:ring-red-100 outline-none transition-all",
                "w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all hover:border-gray-300",
            ),
        ),
        rx.cond(
            error_msg,
            rx.el.p(error_msg, class_name="text-xs text-red-500 mt-1.5 font-medium"),
            rx.cond(
                help_text,
                rx.el.p(
                    help_text, class_name="text-xs text-gray-400 mt-1.5 font-medium"
                ),
                None,
            ),
        ),
        class_name="w-full",
    )


def config_panel() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h2(
                    "Update Server Settings",
                    class_name="text-xl font-bold text-gray-900",
                ),
                rx.el.p(
                    "Define the BIND9 server details and target zone.",
                    class_name="text-sm text-gray-500",
                ),
                class_name="mb-6",
            ),
            rx.el.form(
                rx.el.div(
                    rx.el.div(
                        form_field(
                            "Primary Nameserver",
                            "server_ip",
                            "ns1.example.com or 1.2.3.4",
                            help_text="The IP or FQDN of your BIND9 master.",
                        ),
                        form_field(
                            "DNS Zone",
                            "zone_name",
                            "home.example.com",
                            help_text="The zone configured for dynamic updates.",
                        ),
                        class_name="grid grid-cols-1 md:grid-cols-2 gap-6",
                    ),
                    rx.el.div(
                        form_field(
                            "Record Hostname",
                            "record_name",
                            "nas",
                            help_text="The subdomain to update (e.g. 'nas' for nas.home.example.com).",
                        ),
                        rx.el.div(
                            rx.el.label(
                                "Record Type",
                                class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                            ),
                            rx.el.div(
                                rx.el.select(
                                    rx.el.option("A (IPv4)", value="A"),
                                    rx.el.option("AAAA (IPv6)", value="AAAA"),
                                    on_change=ConfigState.set_record_type,
                                    value=ConfigState.record_type,
                                    class_name="w-full appearance-none px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all cursor-pointer",
                                ),
                                rx.icon(
                                    "chevron-down",
                                    class_name="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none",
                                ),
                                class_name="relative",
                            ),
                            class_name="w-full",
                        ),
                        form_field("TTL (Seconds)", "ttl", "300"),
                        class_name="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6",
                    ),
                    rx.el.div(
                        rx.el.h3(
                            "TSIG Authentication",
                            class_name="text-lg font-bold text-gray-900 mt-8 mb-4 border-t pt-8",
                        ),
                        rx.el.div(
                            form_field("Key Name", "key_name", "tsig-key-name"),
                            rx.el.div(
                                rx.el.label(
                                    "Secret Key",
                                    class_name="block text-sm font-semibold text-gray-700 mb-1.5",
                                ),
                                rx.el.div(
                                    rx.el.input(
                                        name="key_secret",
                                        type=rx.cond(
                                            ConfigState.show_secret, "text", "password"
                                        ),
                                        placeholder="Enter base64 secret...",
                                        default_value=ConfigState.key_secret,
                                        class_name="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-4 focus:ring-blue-100 outline-none transition-all",
                                    ),
                                    rx.el.button(
                                        rx.icon(
                                            rx.cond(
                                                ConfigState.show_secret,
                                                "eye-off",
                                                "eye",
                                            ),
                                            class_name="h-4 w-4",
                                        ),
                                        type="button",
                                        on_click=ConfigState.toggle_secret_visibility,
                                        class_name="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600",
                                    ),
                                    class_name="relative",
                                ),
                                rx.cond(
                                    ConfigState.errors.get("key_secret"),
                                    rx.el.p(
                                        ConfigState.errors["key_secret"],
                                        class_name="text-xs text-red-500 mt-1.5 font-medium",
                                    ),
                                    None,
                                ),
                                class_name="w-full",
                            ),
                            class_name="grid grid-cols-1 md:grid-cols-2 gap-6",
                        ),
                    ),
                    rx.el.div(
                        rx.el.button(
                            "Save & Verify Configuration",
                            type="submit",
                            class_name="px-8 py-3 bg-blue-600 text-white font-bold rounded-xl hover:bg-blue-700 shadow-lg shadow-blue-200 transition-all active:scale-95",
                        ),
                        class_name="mt-10 flex justify-end",
                    ),
                    class_name="space-y-4",
                ),
                on_submit=ConfigState.handle_save,
            ),
            class_name="bg-white p-8 rounded-3xl border border-gray-100 shadow-sm",
        ),
        class_name="max-w-4xl mx-auto py-8",
    )


def config_summary_card() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("lamp_wall_down", class_name="h-10 w-10 text-green-500"),
                    rx.el.div(
                        rx.el.h2(
                            "Configuration Active",
                            class_name="text-xl font-bold text-gray-900",
                        ),
                        rx.el.p(
                            "Client is configured and monitoring IP changes.",
                            class_name="text-sm text-gray-500",
                        ),
                    ),
                    class_name="flex items-center gap-4 mb-8",
                ),
                rx.el.div(
                    rx.el.div(
                        rx.el.span(
                            "Server",
                            class_name="text-xs uppercase tracking-wider text-gray-400 font-bold",
                        ),
                        rx.el.p(
                            ConfigState.server_ip,
                            class_name="text-gray-900 font-semibold",
                        ),
                        class_name="p-4 bg-gray-50 rounded-2xl",
                    ),
                    rx.el.div(
                        rx.el.span(
                            "Target Record",
                            class_name="text-xs uppercase tracking-wider text-gray-400 font-bold",
                        ),
                        rx.el.p(
                            f"{ConfigState.record_name}.{ConfigState.zone_name}",
                            class_name="text-gray-900 font-semibold",
                        ),
                        class_name="p-4 bg-gray-50 rounded-2xl",
                    ),
                    rx.el.div(
                        rx.el.span(
                            "Type / TTL",
                            class_name="text-xs uppercase tracking-wider text-gray-400 font-bold",
                        ),
                        rx.el.p(
                            f"{ConfigState.record_type} / {ConfigState.ttl}s",
                            class_name="text-gray-900 font-semibold",
                        ),
                        class_name="p-4 bg-gray-50 rounded-2xl",
                    ),
                    rx.el.div(
                        rx.el.span(
                            "Auth Key",
                            class_name="text-xs uppercase tracking-wider text-gray-400 font-bold",
                        ),
                        rx.el.p(
                            ConfigState.key_name,
                            class_name="text-gray-900 font-semibold",
                        ),
                        class_name="p-4 bg-gray-50 rounded-2xl",
                    ),
                    class_name="grid grid-cols-2 gap-4",
                ),
                rx.el.button(
                    "Modify Settings",
                    on_click=ConfigState.edit_config,
                    class_name="mt-8 w-full py-3 bg-gray-100 text-gray-700 font-bold rounded-xl hover:bg-gray-200 transition-all",
                ),
                class_name="bg-white p-8 rounded-3xl border border-gray-100 shadow-sm",
            ),
            class_name="max-w-xl mx-auto py-12",
        )
    )