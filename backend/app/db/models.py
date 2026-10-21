"""SQLite tables. Datetimes are stored as UTC and always come back timezone-aware (UTC)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint, types
from sqlmodel import Field, SQLModel


class UTCDateTime(types.TypeDecorator):
    """Accepts aware datetimes, stores UTC, returns aware UTC (SQLite keeps no offset)."""

    impl = types.DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("expected an aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return from_db(value)


def to_db(moment: datetime) -> datetime:
    """Normalise an aware datetime to UTC before storing or comparing."""
    if moment.tzinfo is None:
        raise ValueError("expected an aware datetime")
    return moment.astimezone(UTC)


def from_db(moment: datetime | None) -> datetime | None:
    """Make sure a datetime read back from the database is aware UTC."""
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def utc_field(*, index: bool = False, optional: bool = False) -> Any:
    """A datetime column using UTCDateTime."""
    if optional:
        return Field(default=None, sa_type=UTCDateTime, index=index)
    return Field(sa_type=UTCDateTime, index=index)


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ring_event_id: str = Field(index=True, unique=True)
    device_id: str = Field(index=True)
    type: str
    sub_type: str | None = None
    ts: datetime = utc_field(index=True)
    is_activity: bool = Field(default=False, index=True)
    is_synthetic: bool = False


class Anomaly(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("kind", "day", name="uq_anomaly_kind_day"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "A1"
    day: str = Field(index=True)
    detected_at: datetime = utc_field()
    facts: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    scene_description: str | None = None
    explanation: str | None = None
    explanation_source: str | None = None
    state: str = "DETECTED"
    level_started_at: datetime | None = utc_field(optional=True)
    acked_at: datetime | None = utc_field(optional=True)
    acked_by: str | None = None
    ack_source: str | None = None


class EscalationStep(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    anomaly_id: int = Field(index=True, foreign_key="anomaly.id")
    level: str
    recipient_role: str
    started_at: datetime = utc_field()
    outcome: str


class NotificationLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = utc_field(index=True)
    channel: str
    recipient_role: str
    anomaly_id: int | None = Field(default=None, index=True)
    kind: str = "alert"
    text: str = ""
    status: str = "sent"


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = utc_field(index=True)
    action: str
    reason: str
    outcome: str


class DeviceHealth(SQLModel, table=True):
    device_id: str = Field(primary_key=True)
    status: str = "unknown"
    since: datetime | None = utc_field(optional=True)
    last_checked: datetime | None = utc_field(optional=True)
    caregiver_notified: bool = False
