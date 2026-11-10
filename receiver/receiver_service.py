"""Sample webhook subscriber logic: verify, deduplicate, record.

Self-contained (stdlib sqlite + the same HMAC rules as the platform) so it can run as an
independent service, the way a real external subscriber would.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time

TOLERANCE = int(os.getenv("RECEIVER_TIMESTAMP_TOLERANCE", "300"))
DB_PATH = os.getenv("RECEIVER_DB_PATH", "receiver.db")
ADMIN_TOKEN = os.getenv("RECEIVER_ADMIN_TOKEN", "receiver_dev_token")
DEFAULT_SECRET = os.getenv("RECEIVER_SIGNING_SECRET", "")


class Receiver:
    def __init__(self, db_path: str = DB_PATH, tolerance: int = TOLERANCE):
        self.tolerance = tolerance
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS received_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, event_type TEXT, subscription_id TEXT,
            outcome TEXT, reason TEXT, payload TEXT, received_at REAL);
        CREATE TABLE IF NOT EXISTS processed_events(
            event_id TEXT NOT NULL, subscriber_id TEXT NOT NULL, processed_at REAL,
            PRIMARY KEY(event_id, subscriber_id));
        CREATE TABLE IF NOT EXISTS secrets(subscription_id TEXT PRIMARY KEY, secret TEXT);
        """)

    # -- configuration -------------------------------------------------
    def set_secret(self, subscription_id: str, secret: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO secrets VALUES(?,?)", (subscription_id, secret))

    def _secret_for(self, subscription_id: str | None) -> str | None:
        row = self._db.execute("SELECT secret FROM secrets WHERE subscription_id=?", (subscription_id,)).fetchone()
        return row["secret"] if row else (DEFAULT_SECRET or None)

    # -- processing ----------------------------------------------------
    def handle(self, raw_body: bytes, headers: dict[str, str]) -> tuple[int, dict]:
        h = {k.lower(): v for k, v in headers.items()}
        event_id, event_type = h.get("x-st-event-id", ""), h.get("x-st-event-type", "")
        sub_id = h.get("x-st-subscription-id")
        secret = self._secret_for(sub_id)
        if not secret:
            return self._record(event_id, event_type, sub_id, "rejected", "no_secret_configured", raw_body, 401)
        ok, reason = self.verify(secret, h.get("x-st-timestamp", ""), raw_body, h.get("x-st-signature", ""))
        if not ok:
            return self._record(event_id, event_type, sub_id, "rejected", reason, raw_body, 401)
        try:
            payload = json.loads(raw_body)
            if payload.get("event_id") != event_id:
                return self._record(event_id, event_type, sub_id, "rejected", "event_id_header_mismatch", raw_body, 400)
        except json.JSONDecodeError:
            return self._record(event_id, event_type, sub_id, "rejected", "invalid_json", raw_body, 400)

        subscriber = sub_id or "default"
        with self._lock, self._db:
            cur = self._db.execute("INSERT OR IGNORE INTO processed_events VALUES(?,?,?)",
                                   (event_id, subscriber, time.time()))
            first_time = cur.rowcount == 1
        if not first_time:
            # Duplicate: acknowledge (so the sender stops retrying) but do NOT process again.
            return self._record(event_id, event_type, sub_id, "duplicate", "already_processed", raw_body, 200)
        return self._record(event_id, event_type, sub_id, "accepted", "ok", raw_body, 202)

    def verify(self, secret: str, timestamp: str, body: bytes, signature_header: str) -> tuple[bool, str]:
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False, "invalid_timestamp"
        if abs(time.time() - ts) > self.tolerance:
            return False, "timestamp_out_of_tolerance"
        version, _, provided = (signature_header or "").partition("=")
        if version != "v1" or not provided:
            return False, "malformed_signature"
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, provided):
            return False, "signature_mismatch"
        return True, "ok"

    def _record(self, event_id, event_type, sub_id, outcome, reason, raw_body, status):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO received_events(event_id,event_type,subscription_id,outcome,reason,payload,received_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (event_id, event_type, sub_id, outcome, reason, raw_body.decode("utf-8", "replace")[:20000], time.time()))
        return status, {"outcome": outcome, "reason": reason, "event_id": event_id}

    # -- queries -------------------------------------------------------
    def list_events(self, limit: int = 200) -> list[dict]:
        rows = self._db.execute("SELECT * FROM received_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def get_event(self, event_id: str) -> list[dict]:
        rows = self._db.execute("SELECT * FROM received_events WHERE event_id=? ORDER BY id", (event_id,)).fetchall()
        return [self._row(r) for r in rows]

    def reset(self) -> None:
        with self._lock, self._db:
            self._db.executescript("DELETE FROM received_events; DELETE FROM processed_events;")

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except (TypeError, json.JSONDecodeError):
            pass
        return d
