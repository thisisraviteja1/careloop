"""Audit trail for everything that touches personal data. Never store content, only facts."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlmodel import Session

from app.core import clock
from app.db.models import AuditLog, to_db

logger = logging.getLogger(__name__)

AuditFn = Callable[[str, str, str], None]


def record(session: Session, action: str, reason: str, outcome: str) -> None:
    """Add one audit row. The caller's session commits it."""
    session.add(AuditLog(ts=to_db(clock.now()), action=action, reason=reason, outcome=outcome))
    logger.info("audit action=%s reason=%s outcome=%s", action, reason, outcome)


def recorder(session: Session) -> AuditFn:
    """Bind `record` to a session so adapters can audit without knowing about the database."""
    return lambda action, reason, outcome: record(session, action, reason, outcome)


def null_audit(action: str, reason: str, outcome: str) -> None:
    """An audit sink that only logs (used by scripts that run without a database)."""
    logger.info("audit action=%s reason=%s outcome=%s", action, reason, outcome)
