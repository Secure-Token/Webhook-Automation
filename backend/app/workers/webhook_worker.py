"""Webhook delivery worker: consumes events from the broker and runs the retry poller."""
import logging
import threading

import httpx

from app.broker import Broker
from app.config import get_settings
from app.database import SessionLocal
from app.services import webhook_service

log = logging.getLogger(__name__)


def handle_message(message: dict) -> None:
    db = SessionLocal()
    try:
        webhook_service.process_event_message(db, message)
    finally:
        db.close()


def retry_loop(stop: threading.Event) -> None:
    settings = get_settings()
    while not stop.is_set():
        db = SessionLocal()
        try:
            webhook_service.run_due_retries(db)
        except Exception:  # noqa: BLE001
            log.exception("retry loop error")
        finally:
            db.close()
        stop.wait(settings.webhook_poll_interval)


def run(broker: Broker, stop: threading.Event) -> None:
    log.info("webhook worker started")
    threading.Thread(target=retry_loop, args=(stop,), daemon=True, name="retry-poller").start()
    broker.consume(handle_message, stop)
