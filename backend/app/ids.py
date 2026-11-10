import threading
import uuid
from datetime import datetime, timedelta, timezone

_lock = threading.Lock()
_last = datetime.min.replace(tzinfo=timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    """UTC now, strictly increasing within the process so event ordering is never ambiguous
    (Windows clock resolution can otherwise yield identical timestamps)."""
    global _last
    with _lock:
        now = datetime.now(timezone.utc)
        if now <= _last:
            now = _last + timedelta(microseconds=1)
        _last = now
        return now
