"""The always-on channel: the dashboard shows every message from the NotificationLog table.

The escalation runner writes one NotificationLog row per channel attempt, so delivering to
the dashboard needs no network call and cannot fail.
"""

from __future__ import annotations

from app.notify.base import Recipient, SendResult


class DashboardNotifier:
    name = "dashboard"

    def send(self, recipient: Recipient, text: str, ack_token: str | None = None) -> SendResult:
        return SendResult("sent", "shown on dashboard")
