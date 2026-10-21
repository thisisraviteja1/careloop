"""A2 long silence and away mode."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, select

from app.ai.explainer import neighbor_message, silence_alert
from app.ai.safety import blocked_terms
from app.baseline.gaps import (
    BUCKETS,
    GapBaseline,
    activity_minutes_by_day,
    bucket_for,
    compute_gap_baseline,
    first_alert_minute,
    gap_baselines,
    longest_silence,
)
from app.core.clock import Clock
from app.db.models import Anomaly, AwayPeriod, DeviceHealth, Event
from app.demo.seed import seed_history
from app.detection.detector import duration_text, evaluate_silence
from app.detection.runner import (
    activity_times,
    away_days,
    baseline_for,
    run_detection,
    run_silence_detection,
)

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 10, 22)


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


def ready(bucket: tuple[int, int], typical: int, margin: int = 60) -> GapBaseline:
    return GapBaseline(TODAY, bucket, "ready", typical, typical + margin, 20, margin)


def add_activity(session: Session, moment: datetime, n: int) -> None:
    session.add(Event(ring_event_id=f"p9-{n}", device_id="demo-doorbell", type="motion_detected",
                      sub_type="human", ts=moment, is_activity=True))


# ---- pure gap model ----------------------------------------------------------------------------

def test_buckets_cover_daytime_only() -> None:
    assert bucket_for(7 * 60 + 59) is None
    assert bucket_for(8 * 60) == (480, 720)
    assert bucket_for(19 * 60 + 59) == (960, 1200)
    assert bucket_for(20 * 60) is None


def test_longest_silence_counts_gaps_reaching_into_the_bucket() -> None:
    noon_to_four = (720, 960)
    assert longest_silence([], noon_to_four) is None
    assert longest_silence([1000], noon_to_four) is None  # not seen before the bucket ended
    # seen 7:00 and 9:00, next at 13:00: the 9:00→13:00 gap (240) ends inside the bucket;
    # then silent from 13:00 to the bucket end at 16:00 (180)
    assert longest_silence([420, 540, 780], noon_to_four) == 240
    # a silence still running at the end of the bucket counts in full
    assert longest_silence([420, 600], noon_to_four) == 360
    # a gap that ended before the bucket started doesn't count
    assert longest_silence([420, 700, 730, 900, 950], noon_to_four) == 170


def test_gap_baseline_learning_and_ready() -> None:
    history = {TODAY - timedelta(days=d): [420, 600, 780, 1100] for d in range(1, 6)}
    assert compute_gap_baseline(history, TODAY, (720, 960)).state == "learning"
    history |= {TODAY - timedelta(days=d): [420, 600, 780, 1100] for d in range(6, 12)}
    baseline = compute_gap_baseline(history, TODAY, (720, 960))
    assert baseline.ready and baseline.typical_max == 180 and baseline.threshold == 240
    assert 999 not in [v for v in history.get(TODAY, [])]  # today is never used


def test_evaluate_silence_states() -> None:
    baselines = {b: ready(b, 180) for b in BUCKETS}
    seen = at(TODAY, 9, 30)
    kwargs = {"device_ok": True, "person_name": "Lakshmi"}
    assert evaluate_silence(at(TODAY, 11, 0), baselines, last_seen_today=None,
                            **kwargs).status == "not_seen"
    quiet = evaluate_silence(at(TODAY, 12, 29), baselines, last_seen_today=seen, **kwargs)
    assert quiet.status == "quiet" and quiet.threshold_at == at(TODAY, 13, 30)
    alert = evaluate_silence(at(TODAY, 13, 30), baselines, last_seen_today=seen, **kwargs)
    assert alert.status == "anomaly"
    assert alert.facts["gap_minutes"] == 240 and alert.facts["bucket_start"] == "12:00"
    assert evaluate_silence(at(TODAY, 21, 0), baselines, last_seen_today=seen,
                            **kwargs).status == "outside"
    assert evaluate_silence(at(TODAY, 13, 30), baselines, last_seen_today=seen,
                            device_ok=False, person_name="L").status == "degraded"
    assert evaluate_silence(at(TODAY, 13, 30), baselines, last_seen_today=seen, away=True,
                            **kwargs).status == "away"


def test_first_alert_minute_matches_the_detector() -> None:
    baselines = {(480, 720): ready((480, 720), 300), (720, 960): ready((720, 960), 200),
                 (960, 1200): ready((960, 1200), 150)}
    minute = first_alert_minute(570, baselines)  # last seen 9:30
    assert minute == 570 + 260  # crosses into the noon bucket, whose threshold is 260
    seen = at(TODAY, 9, 30)
    for m, expected in ((minute - 1, "quiet"), (minute, "anomaly")):
        now = datetime.combine(TODAY, time(0), tzinfo=IST) + timedelta(minutes=m)
        assert evaluate_silence(now, baselines, last_seen_today=seen, device_ok=True,
                                person_name="L").status == expected


def test_duration_text() -> None:
    assert duration_text(45) == "45 minutes"
    assert duration_text(60) == "1 hour"
    assert duration_text(181) == "3 hours 1 minute"


# ---- runner on seeded history -----------------------------------------------------------------

@pytest.fixture
def seeded(session: Session, frozen_clock: Clock) -> Session:
    seed_history(session, TODAY, 28, IST)
    session.commit()
    return session


def silence(session: Session) -> object:
    result = run_silence_detection(session, tz=IST, person_name="Lakshmi",
                                   device_id="demo-doorbell")
    session.commit()
    return result


def test_runner_raises_one_a2_and_no_a1(seeded: Session, frozen_clock: Clock) -> None:
    add_activity(seeded, at(TODAY, 7, 5), 1)
    add_activity(seeded, at(TODAY, 9, 30), 2)
    seeded.commit()
    minutes = activity_minutes_by_day(activity_times(seeded, at(TODAY, 9, 31)), IST)
    alert_minute = first_alert_minute(570, gap_baselines(minutes, TODAY))
    assert alert_minute is not None
    alert_at = datetime.combine(TODAY, time(0), tzinfo=IST) + timedelta(minutes=alert_minute)

    frozen_clock.set_time(alert_at - timedelta(minutes=1))
    assert silence(seeded).decision.status == "quiet"
    frozen_clock.set_time(alert_at)
    first = silence(seeded)
    assert first.created and first.anomaly.kind == "A2"
    for _ in range(3):
        frozen_clock.advance(timedelta(minutes=10))
        assert not silence(seeded).created
    a1 = run_detection(seeded, tz=IST, margin=45, person_name="Lakshmi",
                       device_id="demo-doorbell")
    assert a1.decision.status == "normal" and a1.anomaly is None
    assert [a.kind for a in seeded.exec(select(Anomaly)).all()] == ["A2"]


def test_a2_respects_the_device_health_guard(seeded: Session, frozen_clock: Clock) -> None:
    add_activity(seeded, at(TODAY, 7, 5), 1)
    seeded.add(DeviceHealth(device_id="demo-doorbell", status="offline", since=at(TODAY, 8, 0)))
    seeded.commit()
    frozen_clock.set_time(at(TODAY, 19, 59))
    assert silence(seeded).decision.status == "degraded"
    assert seeded.exec(select(Anomaly)).all() == []


# ---- away mode ------------------------------------------------------------------------------

def test_away_day_suppresses_a1_and_a2(seeded: Session, frozen_clock: Clock) -> None:
    seeded.add(AwayPeriod(start=TODAY, end=TODAY + timedelta(days=2), note="visiting",
                          created_at=at(TODAY, 5, 0)))
    seeded.commit()
    frozen_clock.set_time(at(TODAY, 11, 0))
    a1 = run_detection(seeded, tz=IST, margin=45, person_name="Lakshmi",
                       device_id="demo-doorbell")
    assert (a1.decision.status, a1.away, a1.anomaly) == ("away", True, None)
    add_activity(seeded, at(TODAY, 7, 0), 9)
    frozen_clock.set_time(at(TODAY, 19, 50))
    assert silence(seeded).decision.status == "away"
    assert seeded.exec(select(Anomaly)).all() == []
    assert away_days(seeded) == {TODAY, TODAY + timedelta(days=1), TODAY + timedelta(days=2)}


def test_away_days_are_left_out_of_the_baseline(seeded: Session, frozen_clock: Clock) -> None:
    frozen_clock.set_time(at(TODAY, 5, 0))
    before = baseline_for(seeded, at(TODAY, 5, 0), IST, 45)
    # a house-sitter appears at 5:00 AM one Thursday while the person is away
    away_day = TODAY - timedelta(days=7)
    seeded.add(Event(ring_event_id="sitter", device_id="demo-doorbell", type="motion_detected",
                     sub_type="human", ts=at(away_day, 5, 0), is_activity=True))
    seeded.add(AwayPeriod(start=away_day, end=away_day, created_at=at(TODAY, 5, 0)))
    seeded.commit()
    after = baseline_for(seeded, at(TODAY, 5, 0), IST, 45)
    assert 300 not in after.samples
    # with that Thursday excluded only 3 Thursdays remain, so the pooled fallback applies
    assert (before.pooled, before.sample_count) == (False, 4)
    assert (after.pooled, after.sample_count) == (True, 27)


# ---- messages ----------------------------------------------------------------------------

def test_silence_alert_text() -> None:
    facts = {"kind": "A2", "person_name": "Lakshmi", "last_seen_ts": "2026-10-22T09:30:00+05:30",
             "bucket_start": "12:00", "bucket_end": "16:00", "typical_max_gap_minutes": 247,
             "threshold_minutes": 307, "gap_minutes": 312, "sample_count": 28,
             "margin_minutes": 60}
    now = at(TODAY, 14, 42)
    text = silence_alert(facts, "a closed door; no person visible", now, now)
    assert text == (
        "No one has been seen at Lakshmi's front door since 9:30 AM today. Quiet stretches "
        "running into 12 to 4 PM usually last up to about 4 hours 5 minutes; this one has "
        "lasted 5 hours 12 minutes. The doorbell camera appears to show a closed door; no "
        "person visible. Lakshmi hasn't answered a check-in sent at 2:42 PM. Tap below if "
        "you're handling this.")
    assert len(text.split()) <= 70 and blocked_terms(text) == []
    neighbor = neighbor_message(facts, "Suresh", "Meena", now)
    assert "since then" in neighbor and "this morning" not in neighbor
