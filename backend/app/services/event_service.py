"""Event Manager: validates, persists and queues events (transactional outbox).

`emit()` only adds rows to the caller's session. The event is therefore committed
atomically with the business change that caused it, and cannot be lost if the broker
is down: the publisher worker drains `outbox_events` later.
"""
from sqlalchemy.orm import Session

from app.ids import new_id, utcnow
from app.logging_config import correlation_id_var
from app.models import EventRecord, OutboxEvent
from app.schemas.events import DATA_MODELS, SCHEMA_VERSION, EventEnvelope


def emit(
    db: Session,
    event_type: str,
    data: dict,
    *,
    developer_id: str | None = None,
    task_id: str | None = None,
    execution_id: str | None = None,
    claim_id: str | None = None,
) -> EventRecord:
    model = DATA_MODELS.get(event_type)
    if model is None:
        raise ValueError(f"Unknown event type: {event_type}")
    validated = model(**data).model_dump(mode="json")  # raises on schema violations

    cid = correlation_id_var.get()
    envelope = EventEnvelope(
        event_id=new_id("evt"),
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        occurred_at=utcnow(),
        task_id=task_id,
        execution_id=execution_id,
        claim_id=claim_id,
        correlation_id=None if cid == "-" else cid,
        data=validated,
    )
    payload = envelope.model_dump(mode="json")
    record = EventRecord(
        id=envelope.event_id,
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        developer_id=developer_id,
        task_id=task_id,
        execution_id=execution_id,
        claim_id=claim_id,
        payload=payload,
        occurred_at=envelope.occurred_at,
        publication_status="PENDING",
    )
    db.add(record)
    db.add(OutboxEvent(id=new_id("obx"), event_id=record.id, payload=payload, publication_status="PENDING"))
    return record
