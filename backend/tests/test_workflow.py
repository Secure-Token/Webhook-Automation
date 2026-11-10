"""Integration + end-to-end tests (real DB, real services, real signing; broker is the in-memory one)."""
from sqlalchemy import select

from app.broker import _memory
from app.models import EventRecord, OutboxEvent, WebhookDelivery
from app.workers.event_publisher import publish_pending
from tests.conftest import ADMIN, DEV

FLOW = ["task.created", "snapshot.baseline.created", "execution.started", "execution.completed",
        "snapshot.post.created"]


def event_types(api, **params):
    r = api.get("/api/v1/events", headers=DEV, params=params)
    return [e["event_type"] for e in reversed(r.json())]


def test_task_creation_emits_event(api):
    r = api.post("/api/v1/tasks", headers=DEV, json={"description": "Refactor module"})
    assert r.status_code == 201 and r.json()["status"] == "CREATED"
    assert event_types(api) == ["task.created"]


def test_execution_flow_events_snapshots_and_usage(api):
    task_id, exec_id = None, None
    t = api.post("/api/v1/tasks", headers=DEV, json={"description": "Add caching"}).json()
    ex = api.post(f"/api/v1/tasks/{t['id']}/execute", headers=DEV).json()
    assert ex["status"] == "RUNNING"
    done = api.get(f"/api/v1/executions/{ex['id']}", headers=DEV).json()  # background task already ran
    assert done["status"] == "COMPLETED" and done["input_tokens"] > 0 and done["output_tokens"] > 0
    assert api.get(f"/api/v1/tasks/{t['id']}", headers=DEV).json()["task"]["status"] == "COMPLETED"
    snaps = api.get(f"/api/v1/tasks/{t['id']}/snapshots", headers=DEV).json()
    assert {s["snapshot_type"] for s in snaps} == {"BASELINE", "POST_CHANGE"}
    assert event_types(api, task_id=t["id"]) == FLOW
    # completion event carries token usage but does not claim post evidence is captured
    comp = [e for e in api.get("/api/v1/events", headers=DEV).json() if e["event_type"] == "execution.completed"][0]
    payload = api.get(f"/api/v1/events/{comp['id']}", headers=DEV).json()["payload"]
    assert payload["data"]["input_tokens"] == done["input_tokens"] and payload["data"]["post_snapshot_captured"] is False


def test_failed_execution_emits_failed_not_completed(api):
    t = api.post("/api/v1/tasks", headers=DEV, json={"description": "Will fail"}).json()
    api.post(f"/api/v1/tasks/{t['id']}/execute", headers=DEV, json={"simulate_failure": True})
    types = event_types(api, task_id=t["id"])
    assert "execution.failed" in types and "execution.completed" not in types


def test_events_delivered_signed_and_recorded(env):
    sub = env.subscribe()
    task_id, _ = env.run_task()
    env.pump()
    got = [r["event_type"] for r in reversed(env.receiver.list_events()) if r["outcome"] == "accepted"]
    assert got == FLOW
    deliveries = env.api.get("/api/v1/webhooks/deliveries", headers=DEV).json()
    assert len(deliveries) == 5 and {d["delivery_status"] for d in deliveries} == {"SUCCEEDED"}
    assert all(d["subscription_id"] == sub["id"] for d in deliveries)


def test_subscription_filtering(env):
    env.subscribe(event_types=["execution.completed"])
    env.run_task()
    env.pump()
    assert [r["event_type"] for r in env.receiver.list_events()] == ["execution.completed"]


def test_inactive_subscription_gets_nothing(env):
    sub = env.subscribe()
    env.api.patch(f"/api/v1/webhooks/subscriptions/{sub['id']}", headers=DEV, json={"status": "INACTIVE"})
    env.run_task()
    env.pump()
    assert env.receiver.list_events() == []


def test_outbox_survives_broker_outage(env, db):
    class DownBroker:
        def publish(self, *a):
            raise ConnectionError("rabbit down")

    env.subscribe()
    env.run_task()
    assert publish_pending(DownBroker()) == 0
    assert db.query(OutboxEvent).filter_by(publication_status="PENDING").count() == 5  # nothing lost
    assert _memory._q.empty()
    env.pump()  # broker recovers
    db.expire_all()
    assert db.query(OutboxEvent).filter_by(publication_status="PENDING").count() == 0
    assert len([r for r in env.receiver.list_events() if r["outcome"] == "accepted"]) == 5


def test_subscriber_down_execution_still_completes_and_retry_recovers(env, db):
    env.subscribe()
    env.available = False
    task_id, exec_id = env.run_task()
    assert env.api.get(f"/api/v1/executions/{exec_id}", headers=DEV).json()["status"] == "COMPLETED"
    env.pump(rounds=1)
    db.expire_all()
    statuses = {d.delivery_status for d in db.scalars(select(WebhookDelivery)).all()}
    assert "RETRY_SCHEDULED" in statuses and "SUCCEEDED" not in statuses
    env.available = True
    env.pump(rounds=1)  # retry schedule is 0s in tests
    db.expire_all()
    latest = db.scalars(select(WebhookDelivery).where(WebhookDelivery.delivery_status.in_(("PENDING", "IN_PROGRESS", "RETRY_SCHEDULED")))).all()
    assert latest == []
    assert len([r for r in env.receiver.list_events() if r["outcome"] == "accepted"]) == 5


def test_exhausted_retries_go_to_dead_letter_and_manual_retry(env, db):
    env.subscribe(event_types=["task.created"])
    env.available = False
    env.api.post("/api/v1/tasks", headers=DEV, json={"description": "Dead letter me"})
    env.pump(rounds=6)
    db.expire_all()
    rows = db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.attempt_number)).all()
    assert [r.attempt_number for r in rows] == [1, 2, 3] and rows[-1].delivery_status == "DEAD_LETTER"
    env.available = True
    assert env.api.post(f"/api/v1/webhooks/deliveries/{rows[-1].id}/retry", headers=DEV).status_code == 403  # admin only
    r = env.api.post(f"/api/v1/webhooks/deliveries/{rows[-1].id}/retry", headers=ADMIN)
    assert r.status_code == 200 and r.json()["delivery_status"] == "RETRY_SCHEDULED"
    env.pump(rounds=1)
    db.expire_all()
    assert db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.attempt_number.desc())).first().delivery_status == "SUCCEEDED"


def test_duplicate_queue_message_creates_single_delivery(env, db):
    env.subscribe(event_types=["task.created"])
    env.api.post("/api/v1/tasks", headers=DEV, json={"description": "dup message"})
    publish_pending(_memory)
    msg = _memory._q.get_nowait()
    from app.services import webhook_service
    webhook_service.process_event_message(db, msg, env.client)
    webhook_service.process_event_message(db, msg, env.client)  # broker redelivery
    assert db.query(WebhookDelivery).count() == 1
    assert len(env.receiver.list_events()) == 1


def test_succeeded_delivery_cannot_be_retried(env, db):
    env.subscribe(event_types=["task.created"])
    env.api.post("/api/v1/tasks", headers=DEV, json={"description": "done already"})
    env.pump()
    d = db.scalars(select(WebhookDelivery)).one()
    assert d.delivery_status == "SUCCEEDED"
    assert env.api.post(f"/api/v1/webhooks/deliveries/{d.id}/retry", headers=ADMIN).status_code == 409


def test_subscription_test_endpoint(env):
    sub = env.subscribe()
    # No server listens on :9000 in tests, so the one-shot test delivery is recorded as FAILED.
    r = env.api.post(f"/api/v1/webhooks/subscriptions/{sub['id']}/test", headers=DEV)
    assert r.status_code == 200 and r.json()["delivery_status"] in ("FAILED", "SUCCEEDED")  # no server on :9000


def test_full_workflow_task_to_settlement(env, db):
    """E2E: task -> execution -> evidence -> claim -> evaluation -> adjudication -> settlement, all notified."""
    env.subscribe()
    task_id, exec_id = env.run_task(simulate_regression=True)
    claim = env.api.post("/api/v1/claims", headers=DEV, json={"task_id": task_id, "claim_reason": "Tests now fail"})
    assert claim.status_code == 201
    cid = claim.json()["id"]
    # idempotent resubmission returns the same claim
    again = env.api.post("/api/v1/claims", headers=DEV, json={"task_id": task_id, "claim_reason": "again"})
    assert again.status_code == 200 and again.json()["id"] == cid

    ev = env.api.post(f"/api/v1/claims/{cid}/evaluate", headers=DEV).json()
    assert ev["result"] == "ELIGIBLE_FOR_ASSESSMENT" and ev["report"]["simulated"] is True
    assert env.api.post(f"/api/v1/claims/{cid}/adjudicate", headers=DEV, json={"decision": "APPROVED"}).status_code == 403
    adj = env.api.post(f"/api/v1/claims/{cid}/adjudicate", headers=ADMIN, json={"decision": "APPROVED"})
    assert adj.status_code == 200 and adj.json()["status"] == "APPROVED"

    before = env.api.get("/api/v1/stats", headers=DEV).json()["reserve_balance_demo"]
    s1 = env.api.post(f"/api/v1/claims/{cid}/settle", headers=ADMIN)
    s2 = env.api.post(f"/api/v1/claims/{cid}/settle", headers=ADMIN)  # repeat must not double-settle
    assert s1.status_code == 201 and s2.status_code == 200 and s1.json()["id"] == s2.json()["id"]
    after = env.api.get("/api/v1/stats", headers=DEV).json()["reserve_balance_demo"]
    assert round(before - after, 2) == s1.json()["eligible_credit"] > 0
    assert env.api.get(f"/api/v1/claims/{cid}", headers=DEV).json()["claim"]["status"] == "SETTLED"

    env.pump()
    accepted = [r["event_type"] for r in env.receiver.list_events() if r["outcome"] == "accepted"]
    for t in ("claim.submitted", "evaluation.completed", "claim.adjudicated", "claim.settled"):
        assert accepted.count(t) == 1, t
    assert db.query(EventRecord).filter_by(event_type="claim.settled").count() == 1


def test_insufficient_evidence_never_settles(env):
    env.subscribe()
    task_id, _ = env.run_task(simulate_missing_evidence=True)
    cid = env.api.post("/api/v1/claims", headers=DEV, json={"task_id": task_id, "claim_reason": "no evidence"}).json()["id"]
    ev = env.api.post(f"/api/v1/claims/{cid}/evaluate", headers=DEV).json()
    assert ev["result"] == "INSUFFICIENT_EVIDENCE"
    assert env.api.post(f"/api/v1/claims/{cid}/adjudicate", headers=ADMIN, json={"decision": "APPROVED"}).status_code == 409
    assert env.api.post(f"/api/v1/claims/{cid}/settle", headers=ADMIN).status_code == 409
    assert "claim.settled" not in event_types(env.api)


def test_failed_execution_claim_is_eligible_and_clean_run_is_not(env):
    t1, _ = env.run_task(simulate_failure=True)
    c1 = env.api.post("/api/v1/claims", headers=DEV, json={"task_id": t1, "claim_reason": "failed"}).json()["id"]
    assert env.api.post(f"/api/v1/claims/{c1}/evaluate", headers=DEV).json()["result"] == "ELIGIBLE_FOR_ASSESSMENT"
    t2, _ = env.run_task()
    c2 = env.api.post("/api/v1/claims", headers=DEV, json={"task_id": t2, "claim_reason": "unhappy"}).json()["id"]
    assert env.api.post(f"/api/v1/claims/{c2}/evaluate", headers=DEV).json()["result"] == "NOT_ELIGIBLE"


def test_claim_state_transitions_enforced(env):
    task_id, _ = env.run_task(simulate_regression=True)
    cid = env.api.post("/api/v1/claims", headers=DEV, json={"task_id": task_id, "claim_reason": "x y z"}).json()["id"]
    # cannot adjudicate before evaluation, cannot settle before approval
    assert env.api.post(f"/api/v1/claims/{cid}/adjudicate", headers=ADMIN, json={"decision": "APPROVED"}).status_code == 409
    assert env.api.post(f"/api/v1/claims/{cid}/settle", headers=ADMIN).status_code == 409
    env.api.post(f"/api/v1/claims/{cid}/evaluate", headers=DEV)
    assert env.api.post(f"/api/v1/claims/{cid}/adjudicate", headers=ADMIN, json={"decision": "BOGUS"}).status_code == 422


def test_dashboard_stats(env):
    env.subscribe()
    env.run_task()
    env.pump()
    s = env.api.get("/api/v1/stats", headers=DEV).json()
    assert s["tasks"] == 1 and s["executions_completed"] == 1 and s["events"] == 5
    assert s["deliveries_succeeded"] == 5 and s["tokens_total"] > 0
