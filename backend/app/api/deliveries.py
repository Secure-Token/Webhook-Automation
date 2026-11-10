from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventRecord, WebhookDelivery, WebhookSubscription
from app.schemas.api import DeliveryOut
from app.security.authentication import Principal, get_db, get_principal, require_admin
from app.services import webhook_service

router = APIRouter(prefix="/api/v1/webhooks/deliveries", tags=["webhook deliveries"])


def _out(db: Session, d: WebhookDelivery) -> DeliveryOut:
    out = DeliveryOut.model_validate(d)
    sub = db.get(WebhookSubscription, d.subscription_id)
    ev = db.get(EventRecord, d.event_id)
    out.subscriber_name = sub.subscriber_name if sub else None
    out.event_type = ev.event_type if ev else None
    return out


def _visible(db: Session, p: Principal, d: WebhookDelivery | None) -> WebhookDelivery:
    if d is not None:
        sub = db.get(WebhookSubscription, d.subscription_id)
        if p.is_admin or (sub and sub.developer_id == p.developer_id):
            return d
    raise HTTPException(404, "Delivery not found")


@router.get("", response_model=list[DeliveryOut])
def list_deliveries(status: str | None = None, event_id: str | None = None, subscription_id: str | None = None,
                    limit: int = 200, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(min(limit, 1000))
    if not p.is_admin:
        q = q.join(WebhookSubscription, WebhookSubscription.id == WebhookDelivery.subscription_id) \
            .where(WebhookSubscription.developer_id == p.developer_id)
    for col, val in ((WebhookDelivery.delivery_status, status), (WebhookDelivery.event_id, event_id),
                     (WebhookDelivery.subscription_id, subscription_id)):
        if val:
            q = q.where(col == val)
    return [_out(db, d) for d in db.scalars(q).all()]


@router.get("/{delivery_id}", response_model=DeliveryOut)
def get_delivery(delivery_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _out(db, _visible(db, p, db.get(WebhookDelivery, delivery_id)))


@router.post("/{delivery_id}/retry", response_model=DeliveryOut)
def retry_delivery(delivery_id: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = _visible(db, p, db.get(WebhookDelivery, delivery_id))
    return _out(db, webhook_service.request_manual_retry(db, d))
