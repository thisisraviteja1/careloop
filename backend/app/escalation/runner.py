"""Executes the escalation state machine: sends messages, persists steps, records acks."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session

from app import audit
from app.core.tokens import sign_ack
from app.db.models import Anomaly, EscalationStep, NotificationLog, from_db, to_db
from app.escalation.engine import ACKNOWLEDGED, Notify, Waits, can_acknowledge, step
from app.notify.base import Notifier, Recipient, SendResult

logger = logging.getLogger(__name__)

TOKEN_LIFETIME = timedelta(hours=24)
MAX_STEPS_PER_TICK = 4

MessageFn = Callable[[Anomaly, str, datetime], str]  # (anomaly, role, now) -> text


@dataclass(frozen=True)
class AckResult:
    ok: bool
    message: str
    anomaly: Anomaly | None = None


def send_with_retry(notifier: Notifier, recipient: Recipient, text: str,
                    token: str | None) -> SendResult:
    """Try twice. A notifier that raises counts as a failure."""
    result = SendResult("failed", "not attempted")
    for _ in range(2):
        try:
            result = notifier.send(recipient, text, token)
        except Exception as exc:  # a broken adapter must never stop the ladder
            result = SendResult("failed", exc.__class__.__name__)
        if result.ok:
            return result
    return result


def deliver(session: Session, notifiers: Sequence[Notifier], recipient: Recipient, text: str,
            token: str | None, *, anomaly_id: int | None, kind: str, reason: str,
            now: datetime) -> list[SendResult]:
    """Send on every channel, logging each attempt (message text never includes the token)."""
    results = []
    for notifier in notifiers:
        result = send_with_retry(notifier, recipient, text, token)
        results.append(result)
        session.add(NotificationLog(ts=to_db(now), channel=notifier.name,
                                    recipient_role=recipient.role, anomaly_id=anomaly_id,
                                    kind=kind, text=text, status=result.status))
        audit.record(session, "notify.send", reason,
                     f"{notifier.name} to {recipient.role}: {result.status}"
                     + (f" ({result.detail})" if result.status == "failed" else ""))
        if result.status == "failed":
            logger.warning("send via %s to %s failed: %s", notifier.name, recipient.role,
                           result.detail)
    return results


class EscalationRunner:
    def __init__(self, *, waits: Waits, recipients: dict[str, Recipient],
                 notifiers: Sequence[Notifier], message: MessageFn, ack_secret: str) -> None:
        self.waits = waits
        self.recipients = recipients
        self.notifiers = notifiers
        self.message = message
        self.ack_secret = ack_secret

    def token_for(self, anomaly: Anomaly, role: str, now: datetime) -> str:
        return sign_ack(self.ack_secret, anomaly.id, role, now + TOKEN_LIFETIME)

    def advance(self, session: Session, anomaly: Anomaly, now: datetime) -> list[Notify]:
        """Run the state machine until it settles, executing every notify action."""
        done: list[Notify] = []
        for _ in range(MAX_STEPS_PER_TICK):
            result = step(anomaly.state, from_db(anomaly.level_started_at), now, self.waits)
            if result.state == anomaly.state and not result.actions:
                break
            anomaly.state = result.state
            anomaly.level_started_at = result.level_started_at
            for action in result.actions:
                self._notify(session, anomaly, action, result.level_started_at or now)
                done.append(action)
            session.add(anomaly)
        return done

    def _notify(self, session: Session, anomaly: Anomaly, action: Notify,
                started: datetime) -> None:
        recipient = self.recipients[action.role]
        text = self.message(anomaly, action.role, started)
        token = self.token_for(anomaly, action.role, started)
        results = deliver(session, self.notifiers, recipient, text, token,
                          anomaly_id=anomaly.id, kind=f"escalation {action.level}",
                          reason=f"anomaly A1 escalation {action.level}", now=started)
        outcome = "sent" if any(r.status == "sent" for r in results) else "failed"
        session.add(EscalationStep(anomaly_id=anomaly.id, level=action.level,
                                   recipient_role=action.role, started_at=to_db(started),
                                   outcome=outcome))


def acknowledge(session: Session, anomaly_id: int, by_role: str, source: str,
                now: datetime) -> AckResult:
    """Stop the ladder. Safe to call twice: the first ack wins."""
    anomaly = session.get(Anomaly, anomaly_id)
    if anomaly is None:
        audit.record(session, "ack", f"{source} by {by_role}", "rejected: unknown alert")
        return AckResult(False, "This alert no longer exists.")
    if anomaly.state == ACKNOWLEDGED:
        return AckResult(True, "Already handled. Thank you.", anomaly)
    if not can_acknowledge(anomaly.state):
        return AckResult(False, "This alert can't be acknowledged.", anomaly)
    anomaly.state = ACKNOWLEDGED
    anomaly.acked_at = to_db(now)
    anomaly.acked_by = by_role
    anomaly.ack_source = source
    session.add(anomaly)
    audit.record(session, "ack", f"{source} by {by_role}", f"accepted for anomaly {anomaly_id}")
    return AckResult(True, "Thank you. CareLoop has stopped the alert.", anomaly)
