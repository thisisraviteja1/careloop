"""Daytime silence baseline for anomaly A2 "long silence". Pure functions: no I/O.

The day is split into three 4-hour daytime buckets (8 AM–noon, noon–4 PM, 4–8 PM); the
overnight hours (8 PM–8 AM) are excluded, and mornings before the first sighting belong
to A1. For each past day and bucket we take the longest silence that reaches into the
bucket, counted only after the person's first appearance that day. The bucket's typical
maximum is the p90 of those values, and the alert threshold is that plus a margin.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from app.baseline.model import MIN_HISTORY_DAYS, day_key, minutes_after_midnight, percentile

BUCKETS: tuple[tuple[int, int], ...] = ((8 * 60, 12 * 60), (12 * 60, 16 * 60),
                                        (16 * 60, 20 * 60))
DEFAULT_GAP_MARGIN_MINUTES = 60


@dataclass(frozen=True)
class GapBaseline:
    day: date
    bucket: tuple[int, int]
    state: str  # "learning" or "ready"
    typical_max: int | None  # minutes
    threshold: int | None  # minutes of silence that trigger A2
    sample_count: int
    margin: int

    @property
    def ready(self) -> bool:
        return self.state == "ready"


def bucket_for(minute: int) -> tuple[int, int] | None:
    """The daytime bucket containing `minute` (minutes after midnight), or None overnight."""
    return next((b for b in BUCKETS if b[0] <= minute < b[1]), None)


def activity_minutes_by_day(activity: Iterable[datetime], tz: tzinfo) -> dict[date, list[int]]:
    """Sorted activity minutes (after local midnight) for each CareLoop day."""
    result: dict[date, list[int]] = {}
    for moment in activity:
        local = moment.astimezone(tz)
        day = day_key(local)
        result.setdefault(day, []).append(minutes_after_midnight(local, day))
    return {d: sorted(m) for d, m in result.items()}


def longest_silence(minutes: list[int], bucket: tuple[int, int]) -> int | None:
    """Longest silence reaching into `bucket` after the first sighting of the day.

    A gap that started before the bucket counts in full if it ends inside it, the same way
    the live check measures "now minus last seen". None if the person wasn't seen before
    the bucket ended.
    """
    start, end = bucket
    before_end = [m for m in minutes if m < end]
    if not before_end:
        return None
    best = 0
    for previous, current in zip(before_end, before_end[1:], strict=False):
        if current > start:
            best = max(best, current - previous)
    return max(best, end - before_end[-1])  # the silence still running at the bucket's end


def compute_gap_baseline(minutes_by_day: Mapping[date, list[int]], day: date,
                         bucket: tuple[int, int],
                         margin: int = DEFAULT_GAP_MARGIN_MINUTES) -> GapBaseline:
    """Gap baseline for `bucket` on `day` from strictly earlier days."""
    history = {d: m for d, m in minutes_by_day.items() if d < day}
    values = [v for d in sorted(history) if (v := longest_silence(history[d], bucket)) is not None]
    history_days = (day - min(history)).days if history else 0
    if not values or history_days < MIN_HISTORY_DAYS:
        return GapBaseline(day, bucket, "learning", None, None, len(values), margin)
    typical = round(percentile(values, 90))
    return GapBaseline(day, bucket, "ready", typical, typical + margin, len(values), margin)


def gap_baselines(minutes_by_day: Mapping[date, list[int]], day: date,
                  margin: int = DEFAULT_GAP_MARGIN_MINUTES) -> dict[tuple[int, int], GapBaseline]:
    return {b: compute_gap_baseline(minutes_by_day, day, b, margin) for b in BUCKETS}


def first_alert_minute(last_seen: int, baselines: Mapping[tuple[int, int], GapBaseline]
                       ) -> int | None:
    """The first minute after `last_seen` at which A2 would fire, if nobody appears."""
    for minute in range(max(last_seen + 1, BUCKETS[0][0]), BUCKETS[-1][1]):
        baseline = baselines.get(bucket_for(minute))
        if baseline and baseline.ready and minute - last_seen >= baseline.threshold:
            return minute
    return None
