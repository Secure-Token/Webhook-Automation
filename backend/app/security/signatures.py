"""HMAC-SHA256 webhook signing.

Canonical form:
    signed_content = ASCII(timestamp) + b"." + raw_request_body_bytes
    signature      = lowercase_hex(HMAC_SHA256(secret_utf8, signed_content))
    header         = "X-ST-Signature: v1=<signature>"
`timestamp` is Unix epoch seconds (decimal string) and is also sent as X-ST-Timestamp.
The signature covers the exact bytes sent on the wire; verify against the raw body,
never a re-serialised JSON object.
"""
import hashlib
import hmac
import time

SIGNATURE_VERSION = "v1"


def compute_signature(secret: str, timestamp: str | int, body: bytes) -> str:
    signed = str(timestamp).encode() + b"." + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def build_headers(secret: str, body: bytes, event_id: str, event_type: str,
                  delivery_id: str | None = None, subscription_id: str | None = None,
                  attempt: int | None = None, timestamp: int | None = None) -> dict[str, str]:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-ST-Event-ID": event_id,
        "X-ST-Event-Type": event_type,
        "X-ST-Timestamp": ts,
        "X-ST-Signature": f"{SIGNATURE_VERSION}={compute_signature(secret, ts, body)}",
    }
    if delivery_id:
        headers["X-ST-Delivery-ID"] = delivery_id
    if subscription_id:
        headers["X-ST-Subscription-ID"] = subscription_id
    if attempt is not None:
        headers["X-ST-Attempt"] = str(attempt)
    return headers


def verify_signature(secret: str, timestamp: str, body: bytes, signature_header: str,
                     tolerance_seconds: int = 300, now: float | None = None) -> tuple[bool, str]:
    """Returns (ok, reason). Constant-time comparison; rejects stale/future timestamps."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False, "invalid_timestamp"
    if abs((now if now is not None else time.time()) - ts) > tolerance_seconds:
        return False, "timestamp_out_of_tolerance"
    if not signature_header or "=" not in signature_header:
        return False, "malformed_signature"
    version, _, provided = signature_header.partition("=")
    if version != SIGNATURE_VERSION:
        return False, "unsupported_signature_version"
    expected = compute_signature(secret, timestamp, body)
    if not hmac.compare_digest(expected, provided):
        return False, "signature_mismatch"
    return True, "ok"
