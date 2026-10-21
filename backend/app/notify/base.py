"""Notifier interface. Sending happens only in `notify/`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Recipient:
    role: str  # elder | caregiver | neighbor
    name: str
    chat_id: str = ""


@dataclass(frozen=True)
class SendResult:
    status: str  # sent | failed | skipped
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"sent", "skipped"}


class Notifier(Protocol):
    name: str

    def send(self, recipient: Recipient, text: str, ack_token: str | None = None) -> SendResult:
        """Deliver `text`. Raise or return a failed result on error; never block for long."""
        ...
