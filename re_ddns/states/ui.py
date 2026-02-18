import reflex as rx


class UIState(rx.State):
    """Manages global UI states like sidebar navigation."""

    current_page: str = "Dashboard"
    sidebar_open: bool = True

    @rx.event
    def set_page(self, page_name: str):
        self.current_page = page_name

    @rx.event
    def toggle_sidebar(self):
        self.sidebar_open = not self.sidebar_open