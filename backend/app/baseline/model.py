"""Personal routine baseline. Pure functions: no I/O, no clock, no LLM.

A "day" starts at 04:00 local time. For each day we take the time of the first activity
(human motion or doorbell press) as minutes after local midnight of that day. The baseline
for a weekday is the [p10, p90] window of those first-activity times, and the alert
threshold is p90 + margin.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

DAY_START_HOUR = 4
MIN_WEEKDAY_SAMPLES = 4
MIN_HISTORY_DAYS = 7
DEFAULT_MARGIN_MINUTES = 45


@dataclass(frozen=True)
class Baseline:
    """The routine for one day, computed only from days before it."""

    day: date
    state: str  # "learning" or "ready"
    window_start: int | None  # minutes after local midnight
    window_end: int | None
    threshold: int | None
    sample_count: int
    samples: tuple[int, ...]
    pooled: bool
    history_days: int
    margin: int

    @property
    def ready(self) -> bool:
        return self.state == "ready"


def day_key(moment_local: datetime) -> date:
    """The CareLoop day a local moment belongs to (days start at 04:00)."""
    return (moment_local - timedelta(hours=DAY_START_HOUR)).date()


def day_start(day: date, tz: tzinfo) -> datetime:
    """04:00 local on `day`."""
    return datetime.combine(day, time(DAY_START_HOUR), tzinfo=tz)


def at_minutes(day: date, minutes: int, tz: tzinfo) -> datetime:
    """The local moment `minutes` after midnight of `day`."""
    return datetime.combine(day, time(0), tzinfo=tz) + timedelta(minutes=minutes)


def minutes_after_midnight(moment_local: datetime, day: date) -> int:
    """Whole minutes from local midnight of `day` to `moment_local` (wall-clock time)."""
    midnight = datetime.combine(day, time(0))
    return int((moment_local.replace(tzinfo=None) - midnight).total_seconds() // 60)


def first_activity_by_day(activity: Iterable[datetime], tz: tzinfo) -> dict[date, int]:
    """Map each day to the minute of its first activity."""
    result: dict[date, int] = {}
    for moment in activity:
        local = moment.astimezone(tz)
        day = day_key(local)
        minute = minutes_after_midnight(local, day)
        if day not in result or minute < result[day]:
            result[day] = minute
    return result


def percentile(values: Iterable[float], q: float) -> float:
    """Linear-interpolation percentile (the same method as numpy's default)."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of an empty sequence")
    position = (len(ordered) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def compute_baseline(first_by_day: Mapping[date, int], day: date,
                     margin: int = DEFAULT_MARGIN_MINUTES) -> Baseline:
    """Baseline for `day` from strictly earlier days only (no peeking at the day itself)."""
    history = {d: m for d, m in first_by_day.items() if d < day}
    history_days = (day - min(history)).days if history else 0
    same_weekday = sorted(m for d, m in history.items() if d.weekday() == day.weekday())
    pooled = len(same_weekday) < MIN_WEEKDAY_SAMPLES
    samples = tuple(sorted(history.values())) if pooled else tuple(same_weekday)
    state = "ready" if history_days >= MIN_HISTORY_DAYS and samples else "learning"
    if not samples:
        return Baseline(day, state, None, None, None, 0, (), pooled, history_days, margin)
    start = round(percentile(samples, 10))
    end = round(percentile(samples, 90))
    return Baseline(day, state, start, end, end + margin, len(samples), samples, pooled,
                    history_days, margin)
