"""Deterministic synthetic history for the demo. Every row is marked is_synthetic=True."""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, tzinfo

from sqlmodel import Session, delete

from app.db.models import Event
from app.ring.events import is_activity

DEMO_DEVICE_ID = "demo-doorbell"
DEFAULT_SEED = 29


def _at(day: date, minutes: float, tz: tzinfo) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz) + timedelta(minutes=round(minutes))


def first_activity_plan(days: list[date], rng: random.Random) -> dict[date, float]:
    """First-activity minute for each day: about 7:00 ± 15 min, weekends later,
    one late day at 7:40 and two early days at 6:40."""
    plan: dict[date, float] = {}
    for day in days:
        weekend = day.weekday() >= 5
        mean = 7 * 60 + (20 if weekend else 0)
        plan[day] = min(max(rng.gauss(mean, 9), mean - 15), mean + 15)
    if len(days) >= 12:
        plan[days[-10]] = 7 * 60 + 40
        plan[days[3]] = 6 * 60 + 40
        plan[days[-5]] = 6 * 60 + 40
    return plan


def generate_history(end_day: date, days: int, tz: tzinfo, *, device_id: str = DEMO_DEVICE_ID,
                     seed: int = DEFAULT_SEED) -> list[Event]:
    """Events for the `days` days before `end_day` (exclusive), oldest first."""
    rng = random.Random(seed)
    day_list = [end_day - timedelta(days=n) for n in range(days, 0, -1)]
    plan = first_activity_plan(day_list, rng)
    rows: list[Event] = []

    def add(day: date, minutes: float, kind: str, sub: str | None) -> None:
        rows.append(Event(
            ring_event_id=f"synthetic-{day.isoformat()}-{len(rows):04d}",
            device_id=device_id, type=kind, sub_type=sub, ts=_at(day, minutes, tz),
            is_activity=is_activity(kind, sub), is_synthetic=True,
        ))

    for day in day_list:
        add(day, plan[day], "motion_detected", "human")
        for _ in range(rng.randint(3, 6)):
            add(day, rng.uniform(9 * 60, 19 * 60), "motion_detected", "human")
        if rng.random() < 0.3:
            add(day, rng.uniform(10 * 60, 17 * 60), "button_press", None)
        for _ in range(rng.randint(0, 2)):
            add(day, rng.uniform(8 * 60, 20 * 60), "motion_detected", "vehicle")
        evening = 21 * 60 + 40 if day == day_list[-1] else rng.uniform(20 * 60 + 30, 21 * 60 + 50)
        add(day, evening, "motion_detected", "human")
    return sorted(rows, key=lambda e: e.ts)


def seed_history(session: Session, end_day: date, days: int, tz: tzinfo, *,
                 device_id: str = DEMO_DEVICE_ID, seed: int = DEFAULT_SEED) -> int:
    """Replace synthetic events with fresh history ending the day before `end_day`."""
    session.exec(delete(Event).where(Event.is_synthetic == True))  # noqa: E712
    rows = generate_history(end_day, days, tz, device_id=device_id, seed=seed)
    session.add_all(rows)
    session.flush()
    return len(rows)
