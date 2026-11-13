import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import EventRecord, OutboxEvent
from app.schemas.events import EVENT_TYPES
from app.security.signatures import build_headers, compute_signature, verify_signature
from app.services import event_service, webhook_service
from app.services.settlement_service import calculate_credit


def test_event_creation_persists_event_and_outbox(db):
    rec = event_service.emit(db, "task.created", {"status": "CREATED", "project_id": "proj_1"}, task_id="task_1")
    db.commit()
    assert rec.id.startswith("evt_") and rec.event_type == "task.created"
    assert db.get(OutboxEvent, db.query(OutboxEvent).one().id).event_id == rec.id
    p = db.get(EventRecord, rec.id).payload
    assert p["schema_version"] == "1.0" and p["task_id"] == "task_1" and p["occurred_at"]


def test_event_ids_unique(db):
    ids = {event_service.emit(db, "task.created", {"status": "CREATED", "project_id": "p"}).id for _ in range(50)}
    assert len(ids) == 50


def test_event_schema_validation(db):
    with pytest.raises(ValidationError):
        event_service.emit(db, "execution.completed", {"status": "COMPLETED"})
    with pytest.raises(ValidationError):  # unexpected (possibly sensitive) fields are rejected
        event_service.emit(db, "task.created", {"status": "x", "project_id": "p", "prompt": "secret prompt"})
    with pytest.raises(ValueError):
        event_service.emit(db, "nope.event", {})


def test_catalogue_has_ten_events():
    assert len(EVENT_TYPES) == 10


def test_hmac_sign_and_verify():
    body = b'{"a":1}'
    sig = compute_signature("s3cret", 1700000000, body)
    ok, _ = verify_signature("s3cret", "1700000000", body, f"v1={sig}", now=1700000010)
    assert ok
    assert verify_signature("wrong", "1700000000", body, f"v1={sig}", now=1700000010) == (False, "signature_mismatch")
    assert verify_signature("s3cret", "1700000000", b'{"a":2}', f"v1={sig}", now=1700000010)[0] is False
    assert verify_signature("s3cret", "1700000000", body, f"v1={sig}", now=1700009999) == (False, "timestamp_out_of_tolerance")


def test_headers_contain_required_fields():
    h = build_headers("s", b"{}", "evt_1", "task.created", timestamp=1700000000)
    assert h["X-ST-Event-ID"] == "evt_1" and h["X-ST-Timestamp"] == "1700000000"
    assert h["X-ST-Signature"].startswith("v1=")


def test_retry_schedule_and_status_classification():
    s = Settings(webhook_retry_schedule="0,30,120,600,1800", webhook_retry_jitter=0)
    assert s.max_attempts == 5
    assert [webhook_service.retry_delay(n, s) for n in (1, 2, 3, 4)] == [30, 120, 600, 1800]
    assert webhook_service.retry_delay(1, s, retry_after=500) == 500  # Retry-After respected
    c = webhook_service.classify_status
    assert (c(200), c(204), c(500), c(503), c(429), c(408), c(400), c(404), c(302)) == (
        "success", "success", "temporary", "temporary", "temporary", "temporary", "permanent", "permanent", "permanent")


def test_settlement_calculation_limits_and_partial():
    full = calculate_credit(5000, 5.0, 1000, 10000)
    assert full == {"calculated_credit": 25.0, "policy_capped_credit": 25.0, "eligible_credit": 25.0,
                    "settlement_status": "SETTLED"}
    capped = calculate_credit(1_000_000, 5.0, 1000, 10000)
    assert capped["eligible_credit"] == 1000 and capped["settlement_status"] == "PARTIALLY_SETTLED"
    partial = calculate_credit(5000, 5.0, 1000, 10.0)
    assert partial["eligible_credit"] == 10.0 and partial["settlement_status"] == "PARTIALLY_SETTLED"
    assert calculate_credit(5000, 5.0, 1000, 0)["settlement_status"] == "DEFERRED_NO_RESERVE"


def _pending_delivery(db):
    from app.ids import new_id
    from app.models import EventRecord, WebhookDelivery, WebhookSubscription
    from app.models import Developer
    from app.security.secrets_store import store_secret
    dev = db.query(Developer).first()
    ref = store_secret(db, "whsec_test")
    sub = WebhookSubscription(id=new_id("sub"), developer_id=dev.id, subscriber_name="s",
                              endpoint_url="http://localhost:9000/x", event_types=["*"],
                              secret_reference=ref, status="ACTIVE")
    ev = EventRecord(id=new_id("evt"), event_type="webhook.test", schema_version="1", developer_id=None,
                     payload={"event_id": "x"}, occurred_at=__import__("app.ids", fromlist=["utcnow"]).utcnow(),
                     publication_status="PUBLISHED")
    db.add_all([sub, ev]); db.flush()
    return sub, ev


def test_stale_in_progress_delivery_is_recovered(db):
    from datetime import timedelta
    from app.ids import new_id, utcnow
    from app.models import WebhookDelivery
    from app.services import webhook_service as ws
    sub, ev = _pending_delivery(db)
    d = WebhookDelivery(id=new_id("dlv"), event_id=ev.id, subscription_id=sub.id, attempt_number=1,
                        delivery_status="IN_PROGRESS", attempted_at=utcnow() - timedelta(hours=1))
    fresh = WebhookDelivery(id=new_id("dlv"), event_id=ev.id, subscription_id=sub.id, attempt_number=2,
                            delivery_status="IN_PROGRESS", attempted_at=utcnow())
    db.add_all([d, fresh]); db.commit()
    assert ws.recover_stale_in_progress(db) == 1
    db.refresh(d); db.refresh(fresh)
    assert d.delivery_status != "IN_PROGRESS"   # re-attempted (missing secret -> temporary failure)
    assert d.attempted_at > utcnow() - timedelta(minutes=1)
    assert fresh.delivery_status == "IN_PROGRESS"  # recent attempt left alone


def test_retry_creates_successor_atomically(db):
    from app.ids import new_id, utcnow
    from app.models import WebhookDelivery
    from app.services import webhook_service as ws
    sub, ev = _pending_delivery(db)
    d = WebhookDelivery(id=new_id("dlv"), event_id=ev.id, subscription_id=sub.id, attempt_number=1,
                        delivery_status="RETRY_SCHEDULED", next_retry_at=utcnow())
    db.add(d); db.commit()
    assert ws.run_due_retries(db) == 1
    db.refresh(d)
    assert d.delivery_status == "FAILED"
    rows = db.query(WebhookDelivery).filter_by(event_id=ev.id, attempt_number=2).all()
    assert len(rows) == 1
