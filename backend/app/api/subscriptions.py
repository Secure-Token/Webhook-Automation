from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import WebhookSubscription
from app.schemas.api import (DeliveryOut, SubscriptionCreate, SubscriptionCreated, SubscriptionOut,
                             SubscriptionUpdate)
from app.security import endpoint_validation as ev
from app.security.authentication import Principal, get_db, get_principal, require_developer
from app.security.secrets_store import generate_secret, replace_secret, store_secret
from app.services import webhook_service

router = APIRouter(prefix="/api/v1/webhooks/subscriptions", tags=["webhook subscriptions"])


def _validate_url(url: str) -> None:
    try:
        ev.validate_endpoint_url(url)
    except ev.EndpointValidationError as exc:
        raise HTTPException(422, f"Invalid endpoint URL: {exc}") from exc


def _owned(db: Session, p: Principal, sub_id: str) -> WebhookSubscription:
    sub = db.get(WebhookSubscription, sub_id)
    if sub is None or sub.status == "DELETED" or (not p.is_admin and sub.developer_id != p.developer_id):
        raise HTTPException(404, "Subscription not found")
    return sub


@router.post("", response_model=SubscriptionCreated, status_code=201)
def create_subscription(body: SubscriptionCreate, p: Principal = Depends(require_developer),
                        db: Session = Depends(get_db)):
    _validate_url(body.endpoint_url)
    secret = generate_secret()
    ref = store_secret(db, secret)
    sub = WebhookSubscription(id=new_id("sub"), developer_id=p.developer_id, subscriber_name=body.subscriber_name,
                              endpoint_url=body.endpoint_url, secret_reference=ref,
                              event_types=body.event_types, status="ACTIVE")
    db.add(sub)
    db.commit()
    return SubscriptionCreated(**SubscriptionOut.model_validate(sub).model_dump(), signing_secret=secret)


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(WebhookSubscription).where(WebhookSubscription.status != "DELETED") \
        .order_by(WebhookSubscription.created_at.desc())
    if not p.is_admin:
        q = q.where(WebhookSubscription.developer_id == p.developer_id)
    return db.scalars(q).all()


@router.get("/{subscription_id}", response_model=SubscriptionOut)
def get_subscription(subscription_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _owned(db, p, subscription_id)


@router.patch("/{subscription_id}", response_model=SubscriptionOut)
def update_subscription(subscription_id: str, body: SubscriptionUpdate, p: Principal = Depends(get_principal),
                        db: Session = Depends(get_db)):
    sub = _owned(db, p, subscription_id)
    if body.endpoint_url is not None:
        _validate_url(body.endpoint_url)
        sub.endpoint_url = body.endpoint_url
    for field in ("subscriber_name", "event_types", "status"):
        value = getattr(body, field)
        if value is not None:
            setattr(sub, field, value)
    db.commit()
    return sub


@router.delete("/{subscription_id}", status_code=204)
def delete_subscription(subscription_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    sub = _owned(db, p, subscription_id)
    sub.status = "DELETED"  # soft delete keeps delivery history intact
    db.commit()


@router.post("/{subscription_id}/rotate-secret", response_model=SubscriptionCreated)
def rotate_secret(subscription_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    sub = _owned(db, p, subscription_id)
    secret = generate_secret()
    replace_secret(db, sub.secret_reference, secret)
    db.commit()
    return SubscriptionCreated(**SubscriptionOut.model_validate(sub).model_dump(), signing_secret=secret)


@router.post("/{subscription_id}/test", response_model=DeliveryOut)
def test_subscription(subscription_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    sub = _owned(db, p, subscription_id)
    d = webhook_service.send_test_event(db, sub)
    out = DeliveryOut.model_validate(d)
    out.subscriber_name = sub.subscriber_name
    return out
