import json
import logging
import time

import pytest

from app.config import Settings
from app.security.endpoint_validation import EndpointValidationError, validate_endpoint_url
from app.security.signatures import build_headers
from tests.conftest import ADMIN, DEV, RECEIVER_URL


def test_missing_and_invalid_api_key(api):
    assert api.get("/api/v1/tasks").status_code == 401
    assert api.get("/api/v1/tasks", headers={"X-API-Key": "nope"}).status_code == 401
    assert api.get("/api/v1/tasks", headers=DEV).status_code == 200


def test_admin_only_routes_reject_developer_key(api):
    assert api.post("/api/v1/claims/claim_x/adjudicate", headers=DEV, json={"decision": "APPROVED"}).status_code == 403
    assert api.post("/api/v1/claims/claim_x/settle", headers=DEV).status_code == 403


def _signed(env, sub, payload: dict, *, secret=None, ts=None):
    body = json.dumps(payload).encode()
    headers = build_headers(secret or sub["signing_secret"], body, payload["event_id"], payload["event_type"],
                            subscription_id=sub["id"], timestamp=ts)
    return body, headers


PAYLOAD = {"event_id": "evt_manual1", "event_type": "task.created", "data": {}}


def test_receiver_rejects_invalid_signature(env):
    sub = env.subscribe()
    body, headers = _signed(env, sub, PAYLOAD, secret="whsec_attacker_guess")
    status, res = env.receiver.handle(body, headers)
    assert status == 401 and res["reason"] == "signature_mismatch"
    assert env.receiver.list_events()[0]["outcome"] == "rejected"


def test_receiver_rejects_tampered_body(env):
    sub = env.subscribe()
    body, headers = _signed(env, sub, PAYLOAD)
    status, res = env.receiver.handle(body.replace(b"manual1", b"manual2"), headers)
    assert status == 401 and res["reason"] == "signature_mismatch"


def test_receiver_rejects_expired_timestamp(env):
    sub = env.subscribe()
    body, headers = _signed(env, sub, PAYLOAD, ts=int(time.time()) - 3600)
    status, res = env.receiver.handle(body, headers)
    assert status == 401 and res["reason"] == "timestamp_out_of_tolerance"


def test_receiver_dedups_same_event(env):
    sub = env.subscribe()
    body, headers = _signed(env, sub, PAYLOAD)
    assert env.receiver.handle(body, headers)[0] == 202
    status, res = env.receiver.handle(body, headers)
    assert status == 200 and res["outcome"] == "duplicate"
    assert [r["outcome"] for r in env.receiver.list_events()] == ["duplicate", "accepted"]


def test_subscription_cannot_be_modified_by_other_developer(api, env, db):
    from app.ids import new_id
    from app.models import Developer
    from app.security.authentication import hash_api_key
    db.add(Developer(id=new_id("dev"), name="Other", api_key_hash=hash_api_key("other_key")))
    db.commit()
    sub = env.subscribe()
    other = {"X-API-Key": "other_key"}
    url = f"/api/v1/webhooks/subscriptions/{sub['id']}"
    assert api.get(url, headers=other).status_code == 404
    assert api.patch(url, headers=other, json={"status": "INACTIVE"}).status_code == 404
    assert api.delete(url, headers=other).status_code == 404
    assert api.post(url + "/rotate-secret", headers=other).status_code == 404
    assert api.get("/api/v1/webhooks/subscriptions", headers=other).json() == []
    assert api.get(url, headers=ADMIN).status_code == 200


@pytest.mark.parametrize("url", ["ftp://example.com/x", "not a url", "https://", "https://user:pw@example.com/x"])
def test_invalid_endpoint_urls_rejected_on_registration(api, url):
    r = api.post("/api/v1/webhooks/subscriptions", headers=DEV,
                 json={"subscriber_name": "x", "endpoint_url": url, "event_types": ["task.created"]})
    assert r.status_code == 422


def test_unknown_event_type_rejected(api):
    r = api.post("/api/v1/webhooks/subscriptions", headers=DEV,
                 json={"subscriber_name": "x", "endpoint_url": RECEIVER_URL, "event_types": ["bogus.event"]})
    assert r.status_code == 422


def test_production_blocks_private_and_localhost_destinations():
    prod = Settings(environment="production", allow_localhost_webhooks=True)
    for url in ("http://localhost:9000/x", "https://localhost/x", "https://127.0.0.1/x", "https://10.0.0.5/x",
                "https://192.168.1.10/x", "https://169.254.169.254/latest/meta-data", "https://[::1]/x",
                "http://example.com/x"):
        with pytest.raises(EndpointValidationError):
            validate_endpoint_url(url, prod, resolve=False)
    validate_endpoint_url("https://93.184.216.34/hook", prod, resolve=False)  # public https allowed


def test_dev_localhost_requires_explicit_flag():
    off = Settings(environment="development", allow_localhost_webhooks=False)
    with pytest.raises(EndpointValidationError):
        validate_endpoint_url("http://localhost:9000/x", off, resolve=False)
    validate_endpoint_url("http://localhost:9000/x", Settings(allow_localhost_webhooks=True), resolve=False)


def test_secret_returned_once_and_never_in_listings(api):
    r = api.post("/api/v1/webhooks/subscriptions", headers=DEV,
                 json={"subscriber_name": "x", "endpoint_url": RECEIVER_URL, "event_types": ["task.created"]})
    secret = r.json()["signing_secret"]
    assert secret.startswith("whsec_")
    sid = r.json()["id"]
    for resp in (api.get("/api/v1/webhooks/subscriptions", headers=DEV),
                 api.get(f"/api/v1/webhooks/subscriptions/{sid}", headers=DEV),
                 api.patch(f"/api/v1/webhooks/subscriptions/{sid}", headers=DEV, json={"status": "INACTIVE"})):
        assert secret not in resp.text and "signing_secret" not in resp.text
    rotated = api.post(f"/api/v1/webhooks/subscriptions/{sid}/rotate-secret", headers=DEV).json()["signing_secret"]
    assert rotated != secret


def test_secret_stored_encrypted_and_not_logged(api, db, caplog):
    from app.models import WebhookSecret
    caplog.set_level(logging.DEBUG)
    r = api.post("/api/v1/webhooks/subscriptions", headers=DEV,
                 json={"subscriber_name": "x", "endpoint_url": RECEIVER_URL, "event_types": ["task.created"]})
    secret = r.json()["signing_secret"]
    assert secret not in db.query(WebhookSecret).one().ciphertext
    assert secret not in caplog.text


def test_payloads_exclude_prompts_and_sources(env):
    env.run_task()
    for e in env.api.get("/api/v1/events", headers=DEV).json():
        text = json.dumps(env.api.get(f"/api/v1/events/{e['id']}", headers=DEV).json()["payload"])
        assert "Add caching layer" not in text  # task description (prompt) never leaves the platform


def test_non_ascii_api_key_is_401_not_500(api):
    r = api.get("/api/v1/tasks", headers={"X-API-Key": "këy".encode("latin-1")})
    assert r.status_code == 401
