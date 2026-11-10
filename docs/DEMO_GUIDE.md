# Demo Guide

Everything shown is simulated demo data. Fastest path: `python scripts/run_demo.py` (add `--webhook-host receiver` under Docker) runs scenarios A to F and prints PASS/FAIL. The steps below do the same by hand.

## Setup

1. Start the stack (README). For a visible retry delay use a short `WEBHOOK_RETRY_SCHEDULE` such as `0,5,10,20,30` (the `.env.example` default) and `EXECUTION_DELAY_SECONDS=3`.
2. Open the dashboard (http://localhost:5173). Enter the developer key `st_dev_demo_key` and, for admin actions, `st_admin_dev_key` in the header.
3. Reset the receiver log if needed: `curl -X POST localhost:9000/receiver/reset -H 'X-Receiver-Token: receiver_dev_token'`.

Under Docker use the endpoint `http://receiver:9000/receiver/webhooks/secure-tokens`; in lite mode use `http://localhost:9000/receiver/webhooks/secure-tokens`.

## Scenario A: successful execution

1. **Webhooks** page: register the receiver (all events). Copy the secret shown once, then click **Configure sample receiver with this secret**.
2. **Tasks** page: create a task, click **Execute** (the status shows RUNNING, then COMPLETED).
3. Open the task: baseline and post-change snapshot references and token usage are listed.
4. **Events** page: `task.created`, `snapshot.baseline.created`, `execution.started`, `execution.completed`, `snapshot.post.created`. Click an event id to see its payload.
5. **Deliveries** page: all SUCCEEDED. `curl localhost:9000/receiver/events` shows `accepted`.

Expected: task COMPLETED, evidence exists, events received.

## Scenario B: failed delivery and recovery

1. **Webhooks**: register a second subscriber with URL `http://localhost:9999/unavailable` (nothing listens there). Configure its secret in the receiver.
2. Create and execute a task. The task still completes.
3. **Deliveries**: the second subscriber's rows show RETRY_SCHEDULED with a next-retry time and error text (and the Dashboard shows Pending retries).
4. Edit the subscription to the working URL (`PATCH /api/v1/webhooks/subscriptions/{id}` with `{"endpoint_url": "..."}` in Swagger) and click **Retry now** (admin key) or wait for the schedule.
5. Deliveries turn SUCCEEDED; the receiver now has the events.

Expected: execution independent of subscriber availability; delivery recovers. Exhausting the schedule yields DEAD_LETTER, which can also be retried manually.

## Scenario C: invalid signature

```bash
curl -i -X POST localhost:9000/receiver/webhooks/secure-tokens \
  -H 'Content-Type: application/json' -H 'X-ST-Event-ID: evt_bad' -H 'X-ST-Event-Type: task.created' \
  -H "X-ST-Timestamp: $(date +%s)" -H 'X-ST-Signature: v1=deadbeef' -H 'X-ST-Subscription-ID: <sub id>' \
  -d '{"event_id":"evt_bad","event_type":"task.created","data":{}}'
```

Expected: 401; `GET localhost:9000/receiver/events/evt_bad` shows `rejected` / `signature_mismatch`. A timestamp older than 5 minutes is rejected as `timestamp_out_of_tolerance`.

## Scenario D: duplicate event

`python scripts/run_demo.py` performs this (sends one signed request twice). Expected: first `accepted` (202), second `duplicate` (200) and no second processing. Platform-side, queue redelivery never creates a second delivery.

## Scenario E: claim and settlement

1. Tick **regression** in the simulation switches, create and execute a task.
2. Click **Submit claim** on the task. **Claims** page: **Evaluate** -> `ELIGIBLE_FOR_ASSESSMENT` (simulated).
3. With the admin key: **Approve**, then **Settle**. The status becomes SETTLED with a demo credit; the Dashboard reserve decreases. Clicking settle again never double-settles.
4. **Events** / **Deliveries**: `claim.submitted`, `evaluation.completed`, `claim.adjudicated`, `claim.settled` delivered.

## Scenario F: insufficient evidence

1. Tick **missing evidence**, create and execute a task (no post-change snapshot is captured).
2. Submit the claim and **Evaluate** -> `INSUFFICIENT_EVIDENCE`.
3. **Approve** fails with 409 and settlement is refused. No `claim.settled` event exists.

## Troubleshooting

* 401 in the dashboard: check the API keys in the header.
* Receiver says `no_secret_configured`: configure the subscription's secret on the receiver (button on the Webhooks page, or `PUT /receiver/config/secret`).
* Endpoint rejected on registration in production mode: only public https destinations are allowed; set `ENVIRONMENT=development` and `ALLOW_LOCALHOST_WEBHOOKS=true` for local demos.
