"""API-key authentication (prototype). Keys are stored only as SHA-256 hashes."""
import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Developer


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class Principal:
    developer: Developer | None
    is_admin: bool = False

    @property
    def developer_id(self) -> str | None:
        return self.developer.id if self.developer else None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_principal(x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    if hmac.compare_digest(x_api_key.encode(), get_settings().admin_api_key.encode()):
        return Principal(developer=None, is_admin=True)
    dev = db.scalar(select(Developer).where(Developer.api_key_hash == hash_api_key(x_api_key)))
    if dev is None:
        raise HTTPException(401, "Invalid API key")
    return Principal(developer=dev)


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, "Admin API key required")
    return principal


def require_developer(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.developer is None:
        raise HTTPException(403, "A developer API key is required for this operation")
    return principal
