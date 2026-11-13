"""Webhook delivery: fan-out, signing, HTTP POST, retry scheduling, dead-lettering.

Delivery statuses: PENDING, IN_PROGRESS, SUCCEEDED, RETRY_SCHEDULED, FAILED, DEAD_LETTER.
Every attempt is its own row (own delivery id). A row in RETRY_SCHEDULED is turned into FAILED
(that attempt failed) once the next attempt row is created.
A webhook delivery only means "the subscriber was notified"; it is never proof of business success.
"""
import json
import logging
import random
import time
from datetime import timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.ids import new_id, utcnow
from app.models import EventRecord, WebhookDelivery, WebhookSubscription
from app.schemas.events import TEST_EVENT_TYPE
from app.security import endpoint_validation as ev
from app.security.secrets_store import load_secret
from app.security.signatures import build_headers

log = logging.getLogger(__name__)
TERMINAL = {"SUCCEEDED", "FAILED", "DEAD_LETTER"}


def canonical_body(payload: dict) -> bytes:
    """Exact bytes sent on the wire (and signed). Compact JSON, sorted keys, UTF-8."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


def retry_delay(attempt_number: int, settings: Settings, retry_after: float | None = None) -> float:
    """Seconds to wait after failed attempt N before attempt N+1 (schedule[N]), with jitter."""
    sched = settings.retry_schedule
    base = sched[min(attempt_number, len(sched) - 1)]
    jitter = base * settings.webhook_retry_jitter * random.uniform(-1, 1)
    delay = max(0.0, base + jitter)
    if retry_after is not None:
        delay = max(delay, retry_after)
    return delay


def classify_status(code: int) -> str:
    """'success' | 'temporary' | 'permanent'"""
    if 200 <= code < 300:
        return "success"
    if code in (408, 425, 429) or code >= 500:
        return "temporary"
    return "permanent"  # other 4xx and unfollowed 3xx


def matching_subscriptions(db: Session, event: EventRecord) -> list[WebhookSubscription]:
    subs = db.scalars(select(WebhookSubscription).where(WebhookSubscription.status == "ACTIVE")).all()
    return [s for s in subs
            if (event.developer_id is None or s.developer_id == event.developer_id)
            and (event.event_type in s.event_types or "*" in s.event_types)]


def create_initial_deliveries(db: Session, event_id: str) -> list[WebhookDelivery]:
    """Idempotent: a re-delivered queue message never creates duplicate first attempts."""
    event = db.get(EventRecord, event_id)
    if event is None:
        return []
    out = []
    for sub in matching_subscriptions(db, event):
        exists = db.scalar(select(WebhookDelivery.id).where(
            WebhookDelivery.event_id == event_id, WebhookDelivery.subscription_id == sub.id).limit(1))
        if exists:
            continue
        d = WebhookDelivery(id=new_id("dlv"), event_id=event_id, subscription_id=sub.id,
                            attempt_number=1, delivery_status="PENDING")
        db.add(d)
        out.append(d)
    db.commit()
    return out


def _read_limited(resp: httpx.Response, limit: int) -> str:
    buf = b""
    for chunk in resp.iter_bytes():
        buf += chunk
        if len(buf) >= limit:
            break
    return buf[:limit].decode("utf-8", "replace")


def perform_attempt(db: Session, delivery_id: str, client: httpx.Client | None = None,
                    one_shot: bool = False) -> WebhookDelivery:
    settings = get_settings()
    d = db.get(WebhookDelivery, delivery_id)
    if d is None or d.delivery_status not in ("PENDING",):
        return d
    d.delivery_status, d.attempted_at = "IN_PROGRESS", utcnow()
    db.commit()

    event = db.get(EventRecord, d.event_id)
    sub = db.get(WebhookSubscription, d.subscription_id)
    outcome, retry_after = "temporary", None
    try:
        ev.validate_endpoint_url(sub.endpoint_url, settings)  # re-resolves DNS at send time
        secret = load_secret(db, sub.secret_reference)
        body = canonical_body(event.payload)
        headers = build_headers(secret, body, event.id, event.event_type, d.id, sub.id, d.attempt_number)
        own_client = client is None
        client = client or httpx.Client(timeout=settings.webhook_timeout_seconds, follow_redirects=False)
        started = time.monotonic()
        try:
            with client.stream("POST", sub.endpoint_url, content=body, headers=headers) as resp:
                d.response_code = resp.status_code
                d.response_body_summary = _read_limited(resp, settings.webhook_max_response_bytes)
                if resp.headers.get("Retry-After", "").isdigit():
                    retry_after = float(resp.headers["Retry-After"])
                outcome = classify_status(resp.status_code)
                if outcome != "success":
                    d.error_message = f"HTTP {resp.status_code}"
        finally:
            d.duration_ms = int((time.monotonic() - started) * 1000)
            if own_client:
                client.close()
    except ev.EndpointValidationError as exc:
        outcome, d.error_message = "permanent", f"Endpoint rejected: {exc}"
    except httpx.HTTPError as exc:
        outcome, d.error_message = "temporary", f"{type(exc).__name__}: {exc}"[:500]
    except Exception as exc:  # noqa: BLE001
        outcome, d.error_message = "temporary", f"Unexpected {type(exc).__name__}"
        log.exception("unexpected delivery error")

    if outcome == "success":
        d.delivery_status, d.error_message, d.next_retry_at = "SUCCEEDED", None, None
    elif outcome == "permanent":
        d.delivery_status = "FAILED"
    elif one_shot:
        d.delivery_status = "FAILED"
    elif d.attempt_number >= settings.max_attempts:
        d.delivery_status = "DEAD_LETTER"
    else:
        d.delivery_status = "RETRY_SCHEDULED"
        d.next_retry_at = utcnow() + timedelta(seconds=retry_delay(d.attempt_number, settings, retry_after))
    db.commit()
    log.info("webhook attempt", extra={"ctx": {"delivery_id": d.id, "event_id": d.event_id,
                                                "status": d.delivery_status, "code": d.response_code}})
    return d


def process_event_message(db: Session, message: dict, client: httpx.Client | None = None) -> None:
    for d in create_initial_deliveries(db, message["event_id"]):
        perform_attempt(db, d.id, client)
    # Also resume any first attempts left PENDING by a crash before delivery.
    for d in db.scalars(select(WebhookDelivery).where(
            WebhookDelivery.event_id == message["event_id"], WebhookDelivery.delivery_status == "PENDING")).all():
        perform_attempt(db, d.id, client)


def recover_stale_in_progress(db: Session, client: httpx.Client | None = None) -> int:
    """Re-queue attempts stuck IN_PROGRESS (worker crashed mid-send). At-least-once: receivers deduplicate."""
    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.webhook_timeout_seconds * 3 + 30)
    stale = db.scalars(select(WebhookDelivery.id).where(
        WebhookDelivery.delivery_status == "IN_PROGRESS", WebhookDelivery.attempted_at < cutoff)).all()
    count = 0
    for did in stale:
        res = db.execute(update(WebhookDelivery).where(
            WebhookDelivery.id == did, WebhookDelivery.delivery_status == "IN_PROGRESS",
            WebhookDelivery.attempted_at < cutoff).values(delivery_status="PENDING"))
        db.commit()
        if res.rowcount == 1:
            perform_attempt(db, did, client)
            count += 1
    return count


def run_due_retries(db: Session, client: httpx.Client | None = None) -> int:
    count = recover_stale_in_progress(db, client)
    due = db.scalars(select(WebhookDelivery).where(
        WebhookDelivery.delivery_status == "RETRY_SCHEDULED",
        WebhookDelivery.next_retry_at <= utcnow())).all()
    for old in due:
        # Atomic claim so two workers never retry the same attempt. The claim and the next attempt
        # row are committed together: a crash can never leave a failed attempt without a successor.
        res = db.execute(update(WebhookDelivery).where(
            WebhookDelivery.id == old.id, WebhookDelivery.delivery_status == "RETRY_SCHEDULED")
            .values(delivery_status="FAILED"))
        if res.rowcount != 1:
            db.rollback()
            continue
        nxt = WebhookDelivery(id=new_id("dlv"), event_id=old.event_id, subscription_id=old.subscription_id,
                              attempt_number=old.attempt_number + 1, delivery_status="PENDING")
        db.add(nxt)
        db.commit()
        perform_attempt(db, nxt.id, client)
        count += 1
    return count


def request_manual_retry(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """Make a failed / dead-lettered / scheduled delivery eligible immediately (worker picks it up)."""
    from fastapi import HTTPException
    if delivery.delivery_status not in ("RETRY_SCHEDULED", "FAILED", "DEAD_LETTER"):
        raise HTTPException(409, f"Delivery in status {delivery.delivery_status} cannot be retried")
    newer = db.scalar(select(WebhookDelivery.id).where(
        WebhookDelivery.event_id == delivery.event_id, WebhookDelivery.subscription_id == delivery.subscription_id,
        WebhookDelivery.attempt_number > delivery.attempt_number).limit(1))
    if newer:
        raise HTTPException(409, "A newer attempt exists for this delivery")
    delivery.delivery_status, delivery.next_retry_at = "RETRY_SCHEDULED", utcnow()
    db.commit()
    return delivery


def send_test_event(db: Session, sub: WebhookSubscription) -> WebhookDelivery:
    """Synchronous one-shot diagnostic delivery of a `webhook.test` event (not in the catalogue)."""
    from app.schemas.events import SCHEMA_VERSION, EventEnvelope, WebhookTestData
    now = utcnow()
    env = EventEnvelope(event_id=new_id("evt"), event_type=TEST_EVENT_TYPE, occurred_at=now,
                        data=WebhookTestData().model_dump())
    db.add(EventRecord(id=env.event_id, event_type=TEST_EVENT_TYPE, schema_version=SCHEMA_VERSION,
                       developer_id=sub.developer_id, payload=env.model_dump(mode="json"),
                       occurred_at=now, publication_status="NOT_PUBLISHED"))
    d = WebhookDelivery(id=new_id("dlv"), event_id=env.event_id, subscription_id=sub.id,
                        attempt_number=1, delivery_status="PENDING")
    db.add(d)
    db.commit()
    return perform_attempt(db, d.id, one_shot=True)
