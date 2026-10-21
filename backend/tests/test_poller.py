from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.clock import Clock
from app.db.models import DeviceHealth, Event
from app.ring.client import RingClient, RingUnavailableError
from app.ring.events import RingEvent
from app.ring.poller import sync_once

T0 = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)


class FakeRing(RingClient):
    def __init__(self, events: list[RingEvent], status: str = "online",
                 fail_events: bool = False) -> None:
        super().__init__("fixture")
        self.events = events
        self.status = status
        self.fail_events = fail_events
        self.since_seen: list[datetime | None] = []

    def get_device_status(self, device_id: str) -> str:
        return self.status

    def get_events(self, device_id: str, since: datetime | None = None) -> list[RingEvent]:
        self.since_seen.append(since)
        if self.fail_events:
            raise RingUnavailableError("down")
        return [e for e in self.events if since is None or e.ts > since]


def ev(n: int, minutes: int, kind: str = "motion_detected", sub: str | None = "human") -> RingEvent:
    return RingEvent(f"e{n}", "d1", kind, sub, T0 + timedelta(minutes=minutes))


def test_inserts_and_deduplicates(session: Session, frozen_clock: Clock) -> None:
    fake = FakeRing([ev(1, 0), ev(2, 5, "button_press", None), ev(3, 9, sub="vehicle")])
    first = sync_once(session, fake, "d1")
    session.commit()
    assert (first.fetched, first.inserted) == (3, 3)

    fake.events.append(ev(3, 9, sub="vehicle"))  # same Ring ID returned again
    fake.events.append(ev(4, 20))
    second = sync_once(session, fake, "d1")
    session.commit()
    assert second.inserted == 1
    assert fake.since_seen[-1] == T0 + timedelta(minutes=9)

    rows = session.exec(select(Event).order_by(Event.ts)).all()
    assert [r.ring_event_id for r in rows] == ["e1", "e2", "e3", "e4"]
    assert [r.is_activity for r in rows] == [True, True, False, True]


def test_device_health_tracks_status_changes(session: Session, frozen_clock: Clock) -> None:
    fake = FakeRing([])
    sync_once(session, fake, "d1")
    first_since = session.get(DeviceHealth, "d1").since

    frozen_clock.advance(timedelta(minutes=10))
    sync_once(session, fake, "d1")
    assert session.get(DeviceHealth, "d1").since == first_since

    fake.status = "offline"
    frozen_clock.advance(timedelta(minutes=10))
    result = sync_once(session, fake, "d1")
    health = session.get(DeviceHealth, "d1")
    assert result.device_status == "offline"
    assert health.status == "offline"
    assert health.since > first_since


def test_event_fetch_failure_marks_health_error(session: Session, frozen_clock: Clock) -> None:
    result = sync_once(session, FakeRing([], fail_events=True), "d1")
    assert result.device_status == "error"
    assert result.error
    assert session.get(DeviceHealth, "d1").status == "error"
