from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventRecord
from app.schemas.api import EventDetail, EventSummary
from app.security.authentication import Principal, get_db, get_principal

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("", response_model=list[EventSummary])
def list_events(event_type: str | None = None, task_id: str | None = None, claim_id: str | None = None,
                limit: int = 100, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(EventRecord).where(EventRecord.event_type != "webhook.test") \
        .order_by(EventRecord.occurred_at.desc()).limit(min(limit, 500))
    if not p.is_admin:
        q = q.where(EventRecord.developer_id == p.developer_id)
    for col, val in ((EventRecord.event_type, event_type), (EventRecord.task_id, task_id),
                     (EventRecord.claim_id, claim_id)):
        if val:
            q = q.where(col == val)
    return db.scalars(q).all()


@router.get("/{event_id}", response_model=EventDetail)
def get_event(event_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ev = db.get(EventRecord, event_id)
    if ev is None or (not p.is_admin and ev.developer_id != p.developer_id):
        raise HTTPException(404, "Event not found")
    return ev
