"""Thin runner around the pure detector: loads data, applies the device health guard,
and creates at most one A1 anomaly per day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo

from sqlmodel import Session, select

from app.baseline.model import (
    Baseline,
    compute_baseline,
    day_key,
    day_start,
    first_activity_by_day,
)
from app.core import clock
from app.db.models import Anomaly, DeviceHealth, Event, to_db
from app.detection.detector import Decision, evaluate

HEALTHY_STATUSES = {"online", "unknown"}


@dataclass
class DetectionResult:
    decision: Decision
    baseline: Baseline
    anomaly: Anomaly | None  # today's anomaly, if any
    created: bool  # True only on the tick that created it
    last_seen: datetime | None
    health: DeviceHealth | None
    notify_degraded: bool  # caregiver should be told once that monitoring is degraded


def activity_times(session: Session, until: datetime) -> list[datetime]:
    """All activity timestamps up to `until` (later rows, such as scheduled demo events,
    are ignored)."""
    query = select(Event.ts).where(Event.is_activity == True)  # noqa: E712
    rows = session.exec(query.where(Event.ts <= to_db(until)).order_by(Event.ts)).all()
    return list(rows)


def baseline_for(session: Session, now_local: datetime, tz: tzinfo, margin: int) -> Baseline:
    return compute_baseline(first_activity_by_day(activity_times(session, now_local), tz),
                            day_key(now_local), margin)


def run_detection(session: Session, *, tz: tzinfo, margin: int, person_name: str,
                  device_id: str, create: bool = True) -> DetectionResult:
    """One detector tick. With create=False it only reports (used by the status API)."""
    now_local = clock.now().astimezone(tz)
    day = day_key(now_local)
    activity = activity_times(session, now_local)
    baseline = compute_baseline(first_activity_by_day(activity, tz), day, margin)
    start = day_start(day, tz)
    today_first = next((t for t in activity if t >= start), None)
    last_seen = activity[-1] if activity else None

    health = session.get(DeviceHealth, device_id)
    device_ok = health is None or health.status in HEALTHY_STATUSES
    decision = evaluate(now_local, baseline, today_first_activity=today_first,
                        last_seen=last_seen, device_ok=device_ok, person_name=person_name)

    anomaly = session.exec(
        select(Anomaly).where(Anomaly.kind == "A1", Anomaly.day == day.isoformat())
    ).first()
    created = False
    if create and decision.status == "anomaly" and anomaly is None and decision.facts:
        anomaly = Anomaly(kind="A1", day=day.isoformat(), detected_at=clock.now(),
                          facts=decision.facts, state="DETECTED")
        session.add(anomaly)
        session.flush()
        created = True

    notify_degraded = (decision.status == "degraded" and health is not None
                       and not health.caregiver_notified)
    return DetectionResult(decision, baseline, anomaly, created, last_seen, health,
                           notify_degraded)
