"""Webhook signing secrets: generated once, encrypted at rest (Fernet), never logged."""
import secrets

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ids import new_id
from app.models import WebhookSecret


def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key)


def generate_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def store_secret(db: Session, plaintext: str) -> str:
    ref = new_id("sec")
    db.add(WebhookSecret(id=ref, ciphertext=_fernet().encrypt(plaintext.encode()).decode()))
    return ref


def load_secret(db: Session, reference: str) -> str:
    row = db.get(WebhookSecret, reference)
    if row is None:
        raise LookupError("Secret not found")
    return _fernet().decrypt(row.ciphertext.encode()).decode()


def replace_secret(db: Session, reference: str, plaintext: str) -> None:
    row = db.get(WebhookSecret, reference)
    row.ciphertext = _fernet().encrypt(plaintext.encode()).decode()
