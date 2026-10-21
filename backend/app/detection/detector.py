"""Anomaly A1 "late start". Pure: statistics decide, nothing here calls a model or does I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.baseline.model import Baseline, at_minutes

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Decision:
    status: str  # degraded | normal | learning | waiting | anomaly
    reason: str
    threshold_at: datetime | None = None
    facts: dict[str, Any] | None = None


def hhmm(minutes: int) -> str:
    """Minutes after midnight as 24-hour HH:MM (can exceed 24h for after-midnight times)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def evaluate(now_local: datetime, baseline: Baseline, *, today_first_activity: datetime | None,
             last_seen: datetime | None, device_ok: bool, person_name: str) -> Decision:
    """Decide what today's routine looks like at `now_local`."""
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
