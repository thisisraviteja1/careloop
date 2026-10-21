from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, select

from app.baseline.model import (
    compute_baseline,
    day_key,
    first_activity_by_day,
    percentile,
)
from app.core.clock import Clock
from app.db.models import Anomaly, DeviceHealth, Event
from app.demo.seed import generate_history, seed_history
from app.detection.detector import evaluate
from app.detection.runner import run_detection

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 10, 22)  # a Thursday; the frozen_clock fixture starts at 05:00 IST


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


def add_activity(session: Session, moment: datetime, n: int) -> None:
    session.add(Event(ring_event_id=f"t-{n}", device_id="demo-doorbell", type="motion_detected",
                      sub_type="human", ts=moment, is_activity=True))


def detect(session: Session) -> object:
    result = run_detection(session, tz=IST, margin=45, person_name="Lakshmi",
                           device_id="demo-doorbell")
    session.commit()
    return result


@pytest.fixture
def seeded(session: Session, frozen_clock: Clock) -> Session:
    seed_history(session, TODAY, 28, IST)
    session.commit()
    return session


# ---- pure baseline ---------------------------------------------------------------------

def test_percentile_linear_interpolation() -> None:
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 90) == 10
    assert percentile([0, 10], 10) == pytest.approx(1)


def test_day_starts_at_four_am() -> None:
    assert day_key(at(TODAY, 3, 59)) == TODAY - timedelta(days=1)
    assert day_key(at(TODAY, 4, 0)) == TODAY


def test_first_activity_ignores_before_four_am() -> None:
    first = first_activity_by_day([at(TODAY, 2, 0), at(TODAY, 7, 5), at(TODAY, 6, 50)], IST)
    assert first[TODAY] == 6 * 60 + 50
    assert first[TODAY - timedelta(days=1)] == 26 * 60  # 2 AM belongs to the previous day


def test_threshold_is_p90_plus_margin() -> None:
    history = {TODAY - timedelta(days=7 * k): 420 + k for k in range(1, 5)}  # Thursdays
    history |= {TODAY - timedelta(days=d): 400 for d in (1, 2, 3)}
    baseline = compute_baseline(history, TODAY, margin=45)
    assert not baseline.pooled
    assert baseline.sample_count == 4
    assert baseline.window_end == round(percentile([421, 422, 423, 424], 90))
    assert baseline.threshold == baseline.window_end + 45


def test_fewer_than_four_weekday_samples_uses_pooled_stats() -> None:
    history = {TODAY - timedelta(days=d): 420 + d for d in range(1, 15)}  # 2 Thursdays only
    baseline = compute_baseline(history, TODAY)
    assert baseline.pooled
    assert baseline.sample_count == 14
    assert baseline.ready


def test_under_seven_days_is_learning() -> None:
    history = {TODAY - timedelta(days=d): 420 for d in range(1, 7)}
    baseline = compute_baseline(history, TODAY)
    assert baseline.state == "learning"
    decision = evaluate(at(TODAY, 11, 0), baseline, today_first_activity=None, last_seen=None,
                        device_ok=True, person_name="Lakshmi")
    assert decision.status == "learning"


def test_baseline_never_uses_the_day_itself() -> None:
    history = {TODAY - timedelta(days=d): 420 for d in range(1, 30)} | {TODAY: 900}
    assert 900 not in compute_baseline(history, TODAY).samples


def test_seed_is_deterministic_and_synthetic() -> None:
    a = generate_history(TODAY, 28, IST)
    b = generate_history(TODAY, 28, IST)
    assert [(e.ring_event_id, e.ts) for e in a] == [(e.ring_event_id, e.ts) for e in b]
    assert all(e.is_synthetic for e in a)
    days = {day_key(e.ts.astimezone(IST)) for e in a}
    assert len(days) == 28 and max(days) == TODAY - timedelta(days=1)


# ---- runner scenarios on seeded history -----------------------------------------------------

def test_normal_day_no_alert(seeded: Session, frozen_clock: Clock) -> None:
    add_activity(seeded, at(TODAY, 7, 2), 1)
    frozen_clock.set_time(at(TODAY, 11, 0))
    result = detect(seeded)
    assert result.decision.status == "normal"
    assert seeded.exec(select(Anomaly)).all() == []


def test_late_day_within_margin_no_alert(seeded: Session, frozen_clock: Clock) -> None:
    frozen_clock.set_time(at(TODAY, 7, 30))
    assert detect(seeded).decision.status == "waiting"
    add_activity(seeded, at(TODAY, 7, 40), 1)
    frozen_clock.set_time(at(TODAY, 10, 0))
    assert detect(seeded).decision.status == "normal"
    assert seeded.exec(select(Anomaly)).all() == []


def test_missing_day_creates_exactly_one_anomaly_at_threshold(seeded: Session,
                                                              frozen_clock: Clock) -> None:
    frozen_clock.set_time(at(TODAY, 6, 0))
    waiting = detect(seeded)
    assert waiting.decision.status == "waiting"
    threshold_at = waiting.decision.threshold_at

    frozen_clock.set_time(threshold_at - timedelta(minutes=1))
    assert detect(seeded).decision.status == "waiting"

    frozen_clock.set_time(threshold_at)
    result = detect(seeded)
    assert result.created
    facts = result.anomaly.facts
    assert facts["weekday"] == "Thursday"
    assert facts["person_name"] == "Lakshmi"
    assert facts["sample_count"] == 4
    assert facts["last_seen_ts"].startswith(f"{TODAY - timedelta(days=1)}T21:40")
    for key in ("usual_window_start", "usual_window_end", "threshold"):
        assert len(facts[key]) == 5


def test_no_duplicate_anomaly_on_repeated_ticks(seeded: Session, frozen_clock: Clock) -> None:
    frozen_clock.set_time(at(TODAY, 9, 0))
    first = detect(seeded)
    for minutes in (1, 5, 60):
        frozen_clock.advance(timedelta(minutes=minutes))
        assert not detect(seeded).created
    assert first.created
    assert len(seeded.exec(select(Anomaly)).all()) == 1


def test_device_offline_degraded_and_no_anomaly(seeded: Session, frozen_clock: Clock) -> None:
    frozen_clock.set_time(at(TODAY, 6, 30))
    seeded.add(DeviceHealth(device_id="demo-doorbell", status="offline",
                            since=at(TODAY, 6, 30)))
    seeded.commit()
    frozen_clock.set_time(at(TODAY, 10, 0))
    result = detect(seeded)
    assert result.decision.status == "degraded"
    assert result.notify_degraded
    assert seeded.exec(select(Anomaly)).all() == []

    result.health.caregiver_notified = True
    seeded.add(result.health)
    seeded.commit()
    assert not detect(seeded).notify_degraded  # the caregiver is told only once


def test_events_api_error_counts_as_degraded(seeded: Session, frozen_clock: Clock) -> None:
    seeded.add(DeviceHealth(device_id="demo-doorbell", status="error", since=at(TODAY, 5, 0)))
    frozen_clock.set_time(at(TODAY, 10, 0))
    assert detect(seeded).decision.status == "degraded"
