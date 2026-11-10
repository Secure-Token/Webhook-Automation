"""Runs demo scenarios A-F against a running stack and prints PASS/FAIL for each.

Usage (from repo root, with the stack running):
    python scripts/run_demo.py                       # lite mode on localhost
    python scripts/run_demo.py --webhook-host receiver   # docker compose (API reaches receiver by service name)

Requires: pip install httpx   (already in backend requirements)
All execution/evaluation/settlement behaviour is SIMULATED.
"""
import argparse
import hashlib
import hmac
import json
import sys
import time

import httpx

p = argparse.ArgumentParser()
p.add_argument("--api", default="http://localhost:8000")
p.add_argument("--receiver", default="http://localhost:9000", help="receiver URL as seen from this script")
p.add_argument("--webhook-host", default="localhost", help="receiver host as seen from the API/worker")
p.add_argument("--dev-key", default="st_dev_demo_key")
p.add_argument("--admin-key", default="st_admin_dev_key")
p.add_argument("--receiver-token", default="receiver_dev_token")
p.add_argument("--timeout", type=float, default=60)
args = p.parse_args()

DEV = {"X-API-Key": args.dev_key}
ADMIN = {"X-API-Key": args.admin_key}
HOOK_URL = f"http://{args.webhook_host}:9000/receiver/webhooks/secure-tokens"
http = httpx.Client(timeout=15)
results: list[tuple[str, bool, str]] = []


def call(method, url, **kw):
    return http.request(method, url, **kw)


def api(method, path, headers=DEV, **kw):
    r = call(method, args.api + path, headers=headers, **kw)
    return r


def wait_for(pred, what, timeout=None):
    end = time.time() + (timeout or args.timeout)
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {what}")


def subscribe(name, url, events=("*",)):
    r = api("POST", "/api/v1/webhooks/subscriptions",
            json={"subscriber_name": name, "endpoint_url": url, "event_types": list(events)})
    r.raise_for_status()
    sub = r.json()
    call("PUT", args.receiver + "/receiver/config/secret", headers={"X-Receiver-Token": args.receiver_token},
         json={"subscription_id": sub["id"], "secret": sub["signing_secret"]}).raise_for_status()
    return sub


def run_task(**options):
    t = api("POST", "/api/v1/tasks", json={"description": "Demo: add caching layer"}).json()
    ex = api("POST", f"/api/v1/tasks/{t['id']}/execute", json=options).json()
    wait_for(lambda: api("GET", f"/api/v1/executions/{ex['id']}").json()["status"] != "RUNNING", "execution to finish")
    return t["id"], ex["id"]


def received(task_id=None, outcome="accepted", event_type=None):
    rows = call("GET", args.receiver + "/receiver/events?limit=500").json()
    out = []
    for r in rows:
        if r["outcome"] != outcome:
            continue
        if task_id and (r["payload"] or {}).get("task_id") != task_id:
            continue
        if event_type and r["event_type"] != event_type:
            continue
        out.append(r)
    return out


def scenario(name):
    def deco(fn):
        def run():
            try:
                detail = fn()
                results.append((name, True, detail or ""))
            except Exception as exc:  # noqa: BLE001
                results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return run
    return deco


STATE = {}


@scenario("A  Successful execution and event delivery")
def scenario_a():
    sub = subscribe("demo-receiver", HOOK_URL)
    STATE["sub"] = sub
    task_id, exec_id = run_task()
    wanted = ["task.created", "snapshot.baseline.created", "execution.started", "execution.completed", "snapshot.post.created"]
    wait_for(lambda: all(received(task_id, event_type=t) for t in wanted), "5 events at the receiver")
    ds = api("GET", f"/api/v1/webhooks/deliveries?subscription_id={sub['id']}").json()
    ok = [d for d in ds if d["delivery_status"] == "SUCCEEDED"]
    assert len(ok) >= 5, f"expected >=5 successful deliveries, got {len(ok)}"
    return f"task {task_id}: {len(ok)} deliveries SUCCEEDED, receiver accepted all 5 lifecycle events"


@scenario("B  Subscriber outage then retry/recovery")
def scenario_b():
    sub = subscribe("demo-unavailable", f"http://{args.webhook_host}:9999/nothing-listens-here")
    task_id, exec_id = run_task()
    ex = api("GET", f"/api/v1/executions/{exec_id}").json()
    assert ex["status"] == "COMPLETED", "execution must complete even though the subscriber is down"
    sched = wait_for(lambda: [d for d in api("GET", f"/api/v1/webhooks/deliveries?subscription_id={sub['id']}&status=RETRY_SCHEDULED").json()],
                     "retry to be scheduled")
    api("PATCH", f"/api/v1/webhooks/subscriptions/{sub['id']}", json={"endpoint_url": HOOK_URL}).raise_for_status()  # subscriber back
    for d in sched:
        api("POST", f"/api/v1/webhooks/deliveries/{d['id']}/retry", headers=ADMIN)  # retry immediately
    wait_for(lambda: received(task_id, event_type="execution.completed"), "recovered delivery")
    return f"{len(sched)} deliveries were RETRY_SCHEDULED while down; execution COMPLETED regardless; delivered after recovery"


def signed_request(sub, event_id, payload, secret=None, ts=None):
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ts = str(ts or int(time.time()))
    sig = hmac.new((secret or sub["signing_secret"]).encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-ST-Event-ID": event_id, "X-ST-Event-Type": payload["event_type"],
               "X-ST-Timestamp": ts, "X-ST-Signature": f"v1={sig}", "X-ST-Subscription-ID": sub["id"]}
    return body, headers


@scenario("C  Invalid signature rejected")
def scenario_c():
    sub = STATE["sub"]
    eid = f"evt_demo_badsig_{int(time.time())}"
    body, headers = signed_request(sub, eid, {"event_id": eid, "event_type": "task.created", "data": {}}, secret="whsec_wrong")
    r = call("POST", args.receiver + "/receiver/webhooks/secure-tokens", content=body, headers=headers)
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    rec = call("GET", f"{args.receiver}/receiver/events/{eid}").json()
    assert rec[0]["outcome"] == "rejected" and rec[0]["reason"] == "signature_mismatch"
    return "receiver answered 401 and recorded outcome=rejected reason=signature_mismatch"


@scenario("D  Duplicate event deduplicated")
def scenario_d():
    sub = STATE["sub"]
    eid = f"evt_demo_dup_{int(time.time())}"
    body, headers = signed_request(sub, eid, {"event_id": eid, "event_type": "task.created", "data": {}})
    r1 = call("POST", args.receiver + "/receiver/webhooks/secure-tokens", content=body, headers=headers)
    r2 = call("POST", args.receiver + "/receiver/webhooks/secure-tokens", content=body, headers=headers)
    assert r1.json()["outcome"] == "accepted" and r2.json()["outcome"] == "duplicate", (r1.text, r2.text)
    return "first delivery accepted, second recognised as duplicate and not processed again"


@scenario("E  Claim, evaluation, adjudication, settlement")
def scenario_e():
    task_id, _ = run_task(simulate_regression=True)
    claim = api("POST", "/api/v1/claims", json={"task_id": task_id, "claim_reason": "Previously passing tests now fail"}).json()
    cid = claim["id"]
    ev = api("POST", f"/api/v1/claims/{cid}/evaluate").json()
    assert ev["result"] == "ELIGIBLE_FOR_ASSESSMENT", ev
    assert api("POST", f"/api/v1/claims/{cid}/adjudicate", json={"decision": "APPROVED"}).status_code == 403
    assert api("POST", f"/api/v1/claims/{cid}/adjudicate", headers=ADMIN, json={"decision": "APPROVED"}).status_code == 200
    st = api("POST", f"/api/v1/claims/{cid}/settle", headers=ADMIN).json()
    again = api("POST", f"/api/v1/claims/{cid}/settle", headers=ADMIN).json()
    assert st["id"] == again["id"], "settlement must be idempotent"
    for t in ("claim.submitted", "evaluation.completed", "claim.adjudicated", "claim.settled"):
        wait_for(lambda t=t: received(task_id, event_type=t), f"{t} at receiver")
    return f"claim {cid}: {st['settlement_status']} demo credit {st['eligible_credit']} (reserve {st['reserve_before']} -> {st['reserve_after']})"


@scenario("F  Insufficient evidence never auto-settles")
def scenario_f():
    task_id, _ = run_task(simulate_missing_evidence=True)
    cid = api("POST", "/api/v1/claims", json={"task_id": task_id, "claim_reason": "No post-change evidence"}).json()["id"]
    ev = api("POST", f"/api/v1/claims/{cid}/evaluate").json()
    assert ev["result"] == "INSUFFICIENT_EVIDENCE", ev
    assert api("POST", f"/api/v1/claims/{cid}/adjudicate", headers=ADMIN, json={"decision": "APPROVED"}).status_code == 409
    assert api("POST", f"/api/v1/claims/{cid}/settle", headers=ADMIN).status_code == 409
    return f"claim {cid}: INSUFFICIENT_EVIDENCE; approval and settlement were refused (409)"


def main() -> int:
    try:
        http.get(args.api + "/health").raise_for_status()
        http.get(args.receiver + "/health").raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"Stack not reachable: {exc}")
        return 2
    for fn in (scenario_a, scenario_b, scenario_c, scenario_d, scenario_e, scenario_f):
        fn()
    print()
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} scenarios passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
