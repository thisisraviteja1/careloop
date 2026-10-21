"""Anomalies A1 "late start" and A2 "long silence".

Pure: statistics decide, nothing here calls a model or does I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.baseline.gaps import GapBaseline, bucket_for
from app.baseline.model import Baseline, at_minutes, minutes_after_midnight

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Decision:
    status: str  # away | degraded | normal | learning | waiting | anomaly (A2 adds: quiet)
    reason: str
    threshold_at: datetime | None = None
    facts: dict[str, Any] | None = None


def hhmm(minutes: int) -> str:
    """Minutes after midnight as 24-hour HH:MM (can exceed 24h for after-midnight times)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def evaluate(now_local: datetime, baseline: Baseline, *, today_first_activity: datetime | None,
             last_seen: datetime | None, device_ok: bool, person_name: str,
             away: bool = False) -> Decision:
    """Decide what today's routine looks like at `now_local` (anomaly A1, late start)."""
    if away:
        return Decision("away", "Away mode: alerts are paused for today.")
    if not device_ok:
        return Decision("degraded", "Doorbell offline or events unavailable: no alerts raised.")
    if today_first_activity is not None:
        return Decision("normal", "Activity already seen today.")
    if not baseline.ready or baseline.threshold is None:
        return Decision("learning", f"Learning the routine ({baseline.history_days} of 7 days).")

    threshold_at = at_minutes(baseline.day, baseline.threshold, now_local.tzinfo)
    if now_local < threshold_at:
        return Decision("waiting", "No activity yet, still before the usual-time threshold.",
                        threshold_at)

    facts = {
        "kind": "A1",
        "day": baseline.day.isoformat(),
        "person_name": person_name,
        "last_seen_ts": last_seen.astimezone(now_local.tzinfo).isoformat() if last_seen else None,
        "usual_window_start": hhmm(baseline.window_start or 0),
        "usual_window_end": hhmm(baseline.window_end or 0),
        "threshold": hhmm(baseline.threshold),
        "weekday": WEEKDAYS[baseline.day.weekday()],
        "sample_count": baseline.sample_count,
        "pooled": baseline.pooled,
        "margin_minutes": baseline.margin,
    }
    return Decision("anomaly", "No activity by the threshold.", threshold_at, facts)


def duration_text(minutes: int) -> str:
    """'4 hours 10 minutes', '3 hours', '45 minutes'."""
    hours, mins = divmod(int(minutes), 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if mins or not hours:
        parts.append(f"{mins} minute{'s' if mins != 1 else ''}")
    return " ".join(parts)


def evaluate_silence(now_local: datetime, baselines: dict[tuple[int, int], GapBaseline], *,
                     last_seen_today: datetime | None, device_ok: bool, person_name: str,
                     away: bool = False) -> Decision:
    """Anomaly A2, long silence: the person was seen today, then nothing for longer than
    their usual longest quiet stretch in this part of the day, plus a margin."""
    if away:
        return Decision("away", "Away mode: alerts are paused for today.")
    if not device_ok:
        return Decision("degraded", "Doorbell offline or events unavailable: no alerts raised.")
    if last_seen_today is None:
        return Decision("not_seen", "Not seen yet today: the morning check (A1) applies.")
    day = baselines[next(iter(baselines))].day
    now_minute = minutes_after_midnight(now_local, day)
    bucket = bucket_for(now_minute)
    if bucket is None:
        return Decision("outside", "Overnight hours are not checked for long silences.")
    baseline = baselines[bucket]
    if not baseline.ready or baseline.threshold is None:
        return Decision("learning", "Learning the usual quiet stretches.")
    seen = last_seen_today.astimezone(now_local.tzinfo)
    gap = now_minute - minutes_after_midnight(seen, day)
    threshold_at = seen + timedelta(minutes=baseline.threshold)
    if gap < baseline.threshold:
        return Decision("quiet", "Quiet for now, within the usual stretch.", threshold_at)
    facts = {
        "kind": "A2",
        "day": day.isoformat(),
        "person_name": person_name,
        "last_seen_ts": seen.isoformat(),
        "bucket_start": hhmm(bucket[0]),
        "bucket_end": hhmm(bucket[1]),
        "typical_max_gap_minutes": baseline.typical_max,
        "threshold_minutes": baseline.threshold,
        "gap_minutes": gap,
        "sample_count": baseline.sample_count,
        "margin_minutes": baseline.margin,
    }
    return Decision("anomaly", "Silent for longer than usual today.", threshold_at, facts)
