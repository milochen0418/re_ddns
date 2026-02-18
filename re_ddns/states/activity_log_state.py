import reflex as rx
from datetime import datetime
from typing import TypedDict


class LogEntry(TypedDict):
    timestamp: str
    status: str
    message: str
    ip_address: str


class ActivityLogState(rx.State):
    """Manages the activity log history."""

    logs: list[LogEntry] = []

    @rx.event
    def add_log(self, status: str, message: str, ip_address: str = "-"):
        """Adds a new log entry to the history."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = LogEntry(
            timestamp=now, status=status, message=message, ip_address=ip_address
        )
        self.logs.insert(0, new_entry)
        if len(self.logs) > 50:
            self.logs = self.logs[:50]

    @rx.event
    def clear_logs(self):
        """Clears all activity logs."""
        self.logs = []