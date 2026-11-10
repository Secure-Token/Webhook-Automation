# Event Catalogue (schema version 1.0)

These event names are **proposed for this prototype**; the source architecture does not define a webhook subsystem. An event is created only when the underlying business operation has actually happened, in the same database transaction as that operation.

## Envelope

```json
{
  "event_id": "evt_3f9c1a7e2b4d5a60",
  "event_type": "execution.completed",
  "schema_version": "1.0",
  "occurred_at": "2026-11-07T12:00:00Z",
  "task_id": "task_1001",
  "execution_id": "exec_2001",
  "claim_id": null,
  "correlation_id": "a1b2c3d4e5f6",
  "data": { "...event specific..." }
}
```

Payloads carry identifiers and small facts only. They never contain prompts, task descriptions, source files, credentials or whole snapshots; use the referenced records (`evidence_ref`, ids) instead. Models: `backend/app/schemas/events.py` (unknown fields are rejected).

## Delivery headers

| Header | Meaning |
|---|---|
| `X-ST-Event-ID` | stable event id (same on every retry) |
| `X-ST-Event-Type` | event type |
| `X-ST-Timestamp` | Unix seconds used in the signature |
| `X-ST-Signature` | `v1=<hex HMAC-SHA256>` |
| `X-ST-Delivery-ID` | id of this delivery attempt (new per attempt) |
| `X-ST-Subscription-ID` | subscription being served |
| `X-ST-Attempt` | attempt number |

Signature: `hex(HMAC_SHA256(secret_utf8, ASCII(timestamp) + "." + raw_body_bytes))`. The body is compact JSON (`separators=(",",":")`, sorted keys, UTF-8) and the signature covers the exact bytes on the wire: verify the raw body, never re-serialised JSON. Reject timestamps older than 300 s, compare in constant time, and deduplicate on `event_id`.

## Events

| Event | Trigger | `data` fields | Typical subscribers |
|---|---|---|---|
| `task.created` | task accepted | `status`, `project_id` | audit, dashboards |
| `snapshot.baseline.created` | baseline snapshot saved (before execution) | `snapshot_id`, `snapshot_type`, `evidence_ref`, `mock` | evidence/QA consumers |
| `execution.started` | simulated execution begins | `status`, `model`, `provider`, `simulated` | monitoring |
| `execution.completed` | execution finished successfully | `status`, `model`, `provider`, `input_tokens`, `output_tokens`, `usage_record_id`, `simulated`, `post_snapshot_captured` | metering, cost tracking |
| `execution.failed` | execution failed | `status`, `model`, `provider`, `input_tokens`, `output_tokens`, `usage_record_id`, `error_message`, `simulated` | alerting, claims |
| `snapshot.post.created` | post-change snapshot saved | same as baseline | evidence/QA consumers |
| `claim.submitted` | claim registered | `status` | claims desk |
| `evaluation.completed` | simulated evaluation finished | `evaluation_id`, `result`, `evidence_complete`, `simulated` | claims desk |
| `claim.adjudicated` | decision recorded | `decision`, `status`, `evaluation_result` | claims desk, finance |
| `claim.settled` | mock settlement processed | `settlement_id`, `settlement_status`, `eligible_credit`, `calculated_credit`, `simulated`, `demo_data` | finance, developer notification |

Diagnostic only (not in the catalogue, never queued): `webhook.test`, sent by `POST .../subscriptions/{id}/test`.

## Ordering and semantics

* `execution.completed` / `execution.failed` do **not** imply post-change evidence exists (`post_snapshot_captured` is `false`). Evidence is confirmed by `snapshot.post.created`, which follows. If the "missing evidence" switch is used it never arrives.
* Delivery is at-least-once and unordered across subscribers. Use `occurred_at` and `event_id`; make handlers idempotent.
* A delivered webhook means "the subscriber was notified". It is never proof the business outcome succeeded. `evaluation.completed` reports a *simulated* result; eligibility (`claim.adjudicated`) and payment (`claim.settled`) are separate events.
* `claim.settled` values are demo credits, not money.
