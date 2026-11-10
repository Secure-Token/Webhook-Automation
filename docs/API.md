# API (prototype interfaces, not existing Secure Tokens contracts)

Interactive docs: `http://localhost:8000/docs`. Base path `/api/v1`. All routes except `/health` and `/ready` need `X-API-Key`.

* **Developer key** (`DEMO_API_KEY`): own tasks, claims, subscriptions, events, deliveries.
* **Admin key** (`ADMIN_API_KEY`): sees everything; required for adjudicate, settle and delivery retry.

Optional `X-Correlation-ID` is echoed back and attached to logs and event envelopes.

## Error format

```json
{ "error": { "code": 409, "message": "Claim must be evaluated before adjudication", "details": null } }
```

| Code | Meaning |
|---|---|
| 401 | missing/invalid API key |
| 403 | key lacks permission (e.g. developer key on an admin route) |
| 404 | not found, or not owned by the caller |
| 409 | state conflict (running task, claim state, settlement of unapproved claim, retry of a succeeded delivery) |
| 422 | validation error (bad URL, unknown event type, bad decision) |
| 503 | `/ready` and the database is unreachable |

## Endpoints

| Method and path | Notes |
|---|---|
| `GET /health`, `GET /ready` | liveness / DB readiness |
| `POST /tasks` | `{"description": "...", "project_id": null}` -> 201 task; emits `task.created` |
| `GET /tasks`, `GET /tasks/{id}` | detail includes executions |
| `POST /tasks/{id}/execute` | 202. Body (all optional, mock switches): `simulate_failure`, `simulate_regression`, `simulate_missing_evidence`. Captures baseline snapshot, starts execution; completion happens in the background |
| `GET /executions/{id}` | status, tokens, error |
| `GET /tasks/{id}/snapshots` | baseline and post-change (mock) snapshots |
| `POST /claims` | `{"task_id","execution_id"?,"claim_reason"}` -> 201; repeat for the same execution -> 200 with the existing claim (idempotent) |
| `GET /claims`, `GET /claims/{id}` | detail includes evaluation and settlement |
| `POST /claims/{id}/evaluate` | simulated evaluation -> `ELIGIBLE_FOR_ASSESSMENT`, `NOT_ELIGIBLE` or `INSUFFICIENT_EVIDENCE`; idempotent |
| `POST /claims/{id}/adjudicate` | admin. `{"decision":"APPROVED|REJECTED|MANUAL_REVIEW","notes"}`. Needs prior evaluation; `APPROVED` refused unless the result is eligible |
| `POST /claims/{id}/settle` | admin. Only `APPROVED` claims. 201 first time, 200 on repeat (no double settlement) |
| `POST /webhooks/subscriptions` | `{"subscriber_name","endpoint_url","event_types":["*" or names]}` -> 201 including `signing_secret` **once** |
| `GET/PATCH/DELETE /webhooks/subscriptions[/{id}]` | PATCH: `subscriber_name`, `endpoint_url`, `event_types`, `status` (`ACTIVE`/`INACTIVE`); DELETE is a soft delete |
| `POST /webhooks/subscriptions/{id}/rotate-secret` | returns the new secret once |
| `POST /webhooks/subscriptions/{id}/test` | one-shot synchronous `webhook.test` delivery |
| `GET /events`, `GET /events/{id}` | list filters: `event_type`, `task_id`, `claim_id`, `limit`; detail includes payload (owner or admin) |
| `GET /webhooks/deliveries`, `GET /webhooks/deliveries/{id}` | filters: `status`, `event_id`, `subscription_id`. One row per attempt |
| `POST /webhooks/deliveries/{id}/retry` | admin. For `RETRY_SCHEDULED`, `FAILED`, `DEAD_LETTER` latest attempts; the worker retries within about a second |
| `GET /stats` | dashboard counters, including the mock reserve balance |

### Example

```bash
curl -s -X POST localhost:8000/api/v1/tasks -H 'X-API-Key: st_dev_demo_key' -H 'Content-Type: application/json' \
     -d '{"description":"Add caching"}'
curl -s -X POST localhost:8000/api/v1/tasks/TASK_ID/execute -H 'X-API-Key: st_dev_demo_key' \
     -H 'Content-Type: application/json' -d '{"simulate_regression": true}'
```

## Sample receiver (`localhost:9000`)

| Method and path | Notes |
|---|---|
| `POST /receiver/webhooks/secure-tokens` | verifies signature and timestamp; 202 accepted, 200 duplicate, 401 rejected, 400 malformed |
| `GET /receiver/events`, `GET /receiver/events/{event_id}` | log of accepted / rejected / duplicate requests with reasons |
| `PUT /receiver/config/secret` | `X-Receiver-Token`; stores a subscription's secret (the secret is shown to the subscriber only once) |
| `POST /receiver/reset` | `X-Receiver-Token`; clears the log |

## Delivery statuses

`PENDING` -> `IN_PROGRESS` -> `SUCCEEDED` | `RETRY_SCHEDULED` | `FAILED` (permanent, or an attempt that was superseded by a retry) | `DEAD_LETTER` (retries exhausted).
Classification: 2xx success; 408/425/429/5xx and network errors temporary (429 `Retry-After` honoured); other 4xx, redirects and rejected endpoints permanent.
