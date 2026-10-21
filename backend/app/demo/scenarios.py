"""Demo scenarios. Each one sets the clock near today's threshold and scripts what happens.

All demo events are synthetic and marked is_synthetic=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

SCENARIOS = {
    "missed-morning": "No one appears by the threshold. Check-in, caregiver alert, neighbor.",
    "late-but-normal": "First motion at 7:40 AM: later than usual, inside the margin. No alert.",
    "elder-replies": "Check-in sent; the person taps OK two minutes later. The ladder stops.",
    "camera-offline": "The doorbell goes offline. Monitoring degraded notice, no false alarm.",
    "long-silence": "Seen at 7:05 and 9:30 AM, then nothing for longer than usual (A2).",
    "away-day": "Away mode is on for today. The morning passes with no one seen; no alert.",
}
SEEN_AT = ((7, 5), (9, 30))  # long-silence: the morning sightings


@dataclass
class ScheduledEvent:
    at: datetime
    type: str
    sub_type: str | None


@dataclass
class DemoState:
    scenario: str
    started_at: datetime
    finish_after: datetime | None  # finish when the clock passes this (no-alert scenarios)
    device_status: str = "online"
    events: list[ScheduledEvent] = field(default_factory=list)
    elder_ack_delay: timedelta | None = None  # simulated tap after the check-in
    away: bool = False  # away mode on for today
    finished: bool = False
    log: list[dict[str, str]] = field(default_factory=list)


def plan(scenario: str, day_start_local: datetime, threshold_at: datetime,
         silence_alert_at: datetime | None = None) -> DemoState:
    """Build the script for `scenario` on the day starting at `day_start_local` (04:00).

    `threshold_at` is today's A1 threshold; `silence_alert_at` is when A2 would fire after
    the long-silence sightings (needed only for that scenario)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    seven_forty = day_start_local.replace(hour=7, minute=40)
    if scenario == "missed-morning":
        return DemoState(scenario, threshold_at - timedelta(minutes=3), None)
    if scenario == "elder-replies":
        return DemoState(scenario, threshold_at - timedelta(minutes=3), None,
                         elder_ack_delay=timedelta(minutes=2))
    if scenario == "late-but-normal":
        start = min(seven_forty - timedelta(minutes=15), threshold_at - timedelta(minutes=30))
        return DemoState(scenario, start, threshold_at + timedelta(minutes=10),
                         events=[ScheduledEvent(seven_forty, "motion_detected", "human")])
    if scenario == "away-day":
        return DemoState(scenario, threshold_at - timedelta(minutes=3),
                         threshold_at + timedelta(minutes=10), away=True)
    if scenario == "long-silence":
        if silence_alert_at is None:
            raise ValueError("Not enough history for the long-silence check: seed first.")
        events = [ScheduledEvent(day_start_local.replace(hour=h, minute=m), "motion_detected",
                                 "human") for h, m in SEEN_AT]
        return DemoState(scenario, silence_alert_at - timedelta(minutes=3), None, events=events)
    return DemoState(scenario, threshold_at - timedelta(minutes=10),
                     threshold_at + timedelta(minutes=10), device_status="offline")
