"""Turn Ring event-history JSON:API items into CareLoop events.

Field names come from the official `ring-api-helloworld` sample (`attributes.event_type`,
`attributes.start`) and the API docs (`attributes.sub_type`). Event type names differ
between sources (see docs/friction-log.md #3), so both documented spellings count.
Confirm against `fixtures/ring_events.json` from the real probe and trim this list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# (event_type, sub_type or None for "any") pairs that mean "a person was at the door".
HUMAN_MOTION_TYPES = {"motion_detected", "motion", "person_detected"}
HUMAN_SUB_TYPES = {"human", "person"}
DIRECT_ACTIVITY_TYPES = {"button_press", "ding", "motion.human", "person_detected"}


@dataclass(frozen=True)
class RingEvent:
    ring_event_id: str
    device_id: str
    type: str
    sub_type: str | None
    ts: datetime

    @property
    def is_activity(self) -> bool:
        return is_activity(self.type, self.sub_type)


def is_activity(event_type: str, sub_type: str | None) -> bool:
    """Activity = human motion or a doorbell button press."""
    kind = event_type.lower()
    if kind in DIRECT_ACTIVITY_TYPES:
        return True
    return kind in HUMAN_MOTION_TYPES and (sub_type or "").lower() in HUMAN_SUB_TYPES


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO-8601 strings or epoch seconds/milliseconds into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    text = str(value).strip()
    if text.replace(".", "", 1).isdigit():
        return parse_timestamp(float(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_event(item: dict[str, Any], device_id: str) -> RingEvent | None:
    """Parse one JSON:API item. Returns None when the item has no usable id or time."""
    attrs = item.get("attributes") or {}
    event_id = item.get("id") or attrs.get("event_id")
    ts = parse_timestamp(attrs.get("start") or attrs.get("timestamp") or attrs.get("created_at"))
    event_type = attrs.get("event_type") or attrs.get("type") or item.get("type")
    if not event_id or ts is None or not event_type:
        return None
    sub_type = attrs.get("sub_type")
    return RingEvent(
        ring_event_id=str(event_id),
        device_id=device_id,
        type=str(event_type),
        sub_type=str(sub_type) if sub_type else None,
        ts=ts,
    )


def parse_events(body: Any, device_id: str) -> list[RingEvent]:
    """Parse an event-history response body, skipping items we can't read."""
    items = body.get("data", []) if isinstance(body, dict) else []
    events = [parse_event(item, device_id) for item in items if isinstance(item, dict)]
    return sorted((e for e in events if e is not None), key=lambda e: e.ts)
