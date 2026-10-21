"""Thin runner around the pure detectors: loads data, applies away mode and the device
health guard, and creates at most one anomaly of each kind per day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from sqlmodel import Session, select

from app.baseline.gaps import (
    DEFAULT_GAP_MARGIN_MINUTES,
    GapBaseline,
    activity_minutes_by_day,
    gap_baselines,
)
from app.baseline.model import (
    Baseline,
    compute_baseline,
    day_key,
    day_start,
    first_activity_by_day,
)
from app.core import clock
from app.db.models import Anomaly, AwayPeriod, DeviceHealth, Event, to_db
from app.detection.detector import Decision, evaluate, evaluate_silence

HEALTHY_STATUSES = {"online", "unknown"}
MAX_AWAY_DAYS = 366


@dataclass
class DetectionResult:
    decision: Decision
    baseline: Baseline
    anomaly: Anomaly | None  # today's A1 anomaly, if any
    created: bool  # True only on the tick that created it
    last_seen: datetime | None
    health: DeviceHealth | None
    notify_degraded: bool  # caregiver should be told once that monitoring is degraded
    away: bool = False


@dataclass
class SilenceResult:
    decision: Decision
    baselines: dict[tuple[int, int], GapBaseline]
    anomaly: Anomaly | None  # today's A2 anomaly, if any
    created: bool


def activity_times(session: Session, until: datetime) -> list[datetime]:
    """All activity timestamps up to `until` (later rows, such as scheduled demo events,
    are ignored)."""
    query = select(Event.ts).where(Event.is_activity == True)  # noqa: E712
    rows = session.exec(query.where(Event.ts <= to_db(until)).order_by(Event.ts)).all()
    return list(rows)


def away_days(session: Session) -> set[date]:
    """Every day covered by an away period."""
    days: set[date] = set()
    for period in session.exec(select(AwayPeriod)).all():
        span = min((period.end - period.start).days, MAX_AWAY_DAYS)
        days.update(period.start + timedelta(days=n) for n in range(span + 1))
    return days


def baseline_for(session: Session, now_local: datetime, tz: tzinfo, margin: int) -> Baseline:
    away = away_days(session)
    first = {d: m for d, m in first_activity_by_day(activity_times(session, now_local),
                                                    tz).items() if d not in away}
    return compute_baseline(first, day_key(now_local), margin)


def _today_anomaly(session: Session, kind: str, day: date) -> Anomaly | None:
    return session.exec(
        select(Anomaly).where(Anomaly.kind == kind, Anomaly.day == day.isoformat())
    ).first()


def _create(session: Session, kind: str, day: date, facts: dict) -> Anomaly:
    anomaly = Anomaly(kind=kind, day=day.isoformat(), detected_at=clock.now(), facts=facts,
                      state="DETECTED")
    session.add(anomaly)
    session.flush()
    return anomaly


def run_detection(session: Session, *, tz: tzinfo, margin: int, person_name: str,
                  device_id: str, create: bool = True) -> DetectionResult:
    """One A1 tick. With create=False it only reports (used by the status API)."""
    now_local = clock.now().astimezone(tz)
    day = day_key(now_local)
    away = away_days(session)
    activity = activity_times(session, now_local)
    first = {d: m for d, m in first_activity_by_day(activity, tz).items() if d not in away}
    baseline = compute_baseline(first, day, margin)
    start = day_start(day, tz)
    today_first = next((t for t in activity if t >= start), None)
    last_seen = activity[-1] if activity else None

    health = session.get(DeviceHealth, device_id)
    device_ok = health is None or health.status in HEALTHY_STATUSES
    decision = evaluate(now_local, baseline, today_first_activity=today_first,
                        last_seen=last_seen, device_ok=device_ok, person_name=person_name,
                        away=day in away)

    anomaly = _today_anomaly(session, "A1", day)
    created = False
    if create and decision.status == "anomaly" and anomaly is None and decision.facts:
        anomaly = _create(session, "A1", day, decision.facts)
        created = True

    notify_degraded = (decision.status == "degraded" and health is not None
                       and not health.caregiver_notified)
    return DetectionResult(decision, baseline, anomaly, created, last_seen, health,
                           notify_degraded, day in away)


def run_silence_detection(session: Session, *, tz: tzinfo, person_name: str, device_id: str,
                          margin: int = DEFAULT_GAP_MARGIN_MINUTES,
                          create: bool = True) -> SilenceResult:
    """One A2 tick: a long silence after the person was seen today."""
    now_local = clock.now().astimezone(tz)
    day = day_key(now_local)
    away = away_days(session)
    activity = activity_times(session, now_local)
    minutes = {d: m for d, m in activity_minutes_by_day(activity, tz).items() if d not in away}
    baselines = gap_baselines(minutes, day, margin)
    start = day_start(day, tz)
    today = [t for t in activity if t >= start]
    health = session.get(DeviceHealth, device_id)
    device_ok = health is None or health.status in HEALTHY_STATUSES
    decision = evaluate_silence(now_local, baselines,
                                last_seen_today=today[-1] if today else None,
                                device_ok=device_ok, person_name=person_name,
                                away=day in away)
    anomaly = _today_anomaly(session, "A2", day)
    created = False
    if create and decision.status == "anomaly" and anomaly is None and decision.facts:
        anomaly = _create(session, "A2", day, decision.facts)
        created = True
    return SilenceResult(decision, baselines, anomaly, created)
