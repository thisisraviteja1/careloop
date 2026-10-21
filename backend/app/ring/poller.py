"""Fetch new Ring events into the database and keep device health current.

Run once from the command line:  python -m app.ring.poller --once
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, func, select

from app.core import clock
from app.db.models import DeviceHealth, Event, from_db, to_db
from app.ring.client import RingAuthError, RingClient, RingError

logger = logging.getLogger(__name__)

# The first sync of an empty database looks back this far.
INITIAL_LOOKBACK = timedelta(days=60)


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    inserted: int
    device_status: str
    error: str | None = None


def update_health(session: Session, device_id: str, status: str) -> DeviceHealth:
    """Record the device status; `since` changes only when the status changes."""
    current = clock.now()
    health = session.get(DeviceHealth, device_id)
    if health is None:
        health = DeviceHealth(device_id=device_id, status=status, since=to_db(current))
    elif health.status != status:
        health.status = status
        health.since = to_db(current)
        if status == "online":
            health.caregiver_notified = False
    health.last_checked = to_db(current)
    session.add(health)
    return health


def sync_once(session: Session, client: RingClient, device_id: str) -> SyncResult:
    """Pull events after the stored cursor (newest stored event), de-duplicated by Ring ID."""
    try:
        status = client.get_device_status(device_id)
    except RingAuthError:
        raise
    except RingError as exc:
        update_health(session, device_id, "error")
        return SyncResult(0, 0, "error", str(exc))

    cursor = session.exec(select(func.max(Event.ts)).where(Event.device_id == device_id)).one()
    since = from_db(cursor) or clock.now() - INITIAL_LOOKBACK
    try:
        events = client.get_events(device_id, since=since)
    except RingAuthError:
        raise
    except RingError as exc:
        update_health(session, device_id, "error")
        return SyncResult(0, 0, "error", str(exc))

    update_health(session, device_id, status)
    ids = [e.ring_event_id for e in events]
    known = set(session.exec(
        select(Event.ring_event_id).where(Event.ring_event_id.in_(ids))
    ).all()) if ids else set()
    inserted = 0
    for event in events:
        if event.ring_event_id in known:
            continue
        known.add(event.ring_event_id)
        session.add(Event(
            ring_event_id=event.ring_event_id, device_id=device_id, type=event.type,
            sub_type=event.sub_type, ts=to_db(event.ts), is_activity=event.is_activity,
        ))
        inserted += 1
    logger.info("sync: fetched=%d inserted=%d status=%s", len(events), inserted, status)
    return SyncResult(len(events), inserted, status)


def main() -> int:
    from app.config import get_settings
    from app.db.session import init_engine, session_scope

    parser = argparse.ArgumentParser(description="Sync Ring events into the CareLoop database")
    parser.add_argument("--once", action="store_true", help="Run one sync and exit")
    parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    init_engine(settings.database_url)
    client = RingClient(settings.ring_mode, settings.ring_access_token)
    try:
        device_id = settings.ring_device_id or client.first_device_id()
        if not device_id:
            logger.error("No Ring device is visible to this token. Nothing to sync.")
            return 3
        with session_scope() as session:
            result = sync_once(session, client, device_id)
    except RingAuthError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        client.close()
    logger.info("Done: %s", result)
    return 0 if result.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
