"""Outbox publisher: moves committed events from `outbox_events` to the broker.

If the broker is down, rows stay PENDING and are published after recovery, so no event is lost.
At-least-once: a crash between publish and commit republishes; consumers deduplicate.
"""
import logging
import threading

from sqlalchemy import select

from app.broker import Broker
from app.config import get_settings
from app.database import SessionLocal
from app.ids import utcnow
from app.models import EventRecord, OutboxEvent

log = logging.getLogger(__name__)


def publish_pending(broker: Broker, batch: int = 50) -> int:
    db = SessionLocal()
    published = 0
    try:
        q = select(OutboxEvent).where(OutboxEvent.publication_status == "PENDING") \
            .order_by(OutboxEvent.created_at).limit(batch)
        if db.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        for row in db.scalars(q).all():
            try:
                broker.publish(row.payload["event_type"], row.payload)
            except Exception as exc:  # noqa: BLE001 - broker down: leave PENDING, retry later
                row.attempts += 1
                row.last_error = str(exc)[:300]
                db.commit()
                log.warning("outbox publish failed: %s", exc)
                break
            row.publication_status, row.published_at = "PUBLISHED", utcnow()
            rec = db.get(EventRecord, row.event_id)
            if rec:
                rec.publication_status = "PUBLISHED"
            db.commit()
            published += 1
        return published
    finally:
        db.close()


def run(broker: Broker, stop: threading.Event) -> None:
    interval = get_settings().outbox_poll_interval
    log.info("event publisher started")
    while not stop.is_set():
        try:
            if publish_pending(broker) == 0:
                stop.wait(interval)
        except Exception:  # noqa: BLE001
            log.exception("publisher loop error")
            stop.wait(2)
