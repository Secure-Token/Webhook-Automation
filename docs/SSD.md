# System Specification / Design: Webhook Automation Prototype

## 1. Components

```
 Developer/Dashboard
        |  REST (X-API-Key)
        v
 +-------------- API (FastAPI) --------------+       +------------------+
 | tasks | execution(sim) | snapshots(mock)  |       |   PostgreSQL     |
 | claims | evaluation(sim) | settlement(sim)|<----->| business tables  |
 | subscriptions | events | deliveries       |       | event_records    |
 +----------------------+--------------------+       | outbox_events    |
   Event Manager: event_records + outbox_events      | webhook_*        |
   written in the SAME transaction as the change     +--------^---------+
                         |                                    |
          Publisher worker (poll outbox, SKIP LOCKED)         |
                         v                                    |
                  RabbitMQ topic exchange `st.events`         |
                  durable queue `st.webhook.delivery`         |
                         v                                    |
          Delivery worker: fan-out, sign, POST (HTTPX) -------+
          + retry poller (reads next_retry_at)
                         |  HTTPS/HTTP webhook
                         v
              External subscriber (sample receiver)
              verify HMAC + timestamp, dedup, record
```

Internal communication uses direct calls and RabbitMQ. HTTP webhooks are used only for external subscribers.

## 2. Event flow and reliability

1. A service calls `event_service.emit()`, which validates the data against its Pydantic model and adds an `event_records` row and an `outbox_events` row to the caller's session. The caller's commit makes the business change and the event atomic.
2. `event_publisher` polls PENDING outbox rows (Postgres `FOR UPDATE SKIP LOCKED`), publishes with publisher confirms and persistent delivery, then marks the row and event `PUBLISHED`. If the broker is down the row stays PENDING and is published after recovery (`test_outbox_survives_broker_outage`). A crash between publish and commit republishes: delivery is **at-least-once**.
3. The delivery worker consumes with manual acks. For each active subscription of the event's developer whose filter matches, it creates attempt 1 (idempotent: an existing delivery for the event+subscription is not recreated), signs and POSTs.
4. Outcome handling: success -> `SUCCEEDED`; permanent (other 4xx, redirects, endpoint validation failure) -> `FAILED`; temporary (network/timeout, 408/425/429/5xx) -> `RETRY_SCHEDULED` with `next_retry_at`, or `DEAD_LETTER` once `max_attempts` is reached.
5. Retries are scheduled in PostgreSQL rather than RabbitMQ delay queues: simpler, durable and visible in the UI. The poller atomically claims due rows (`UPDATE ... WHERE status='RETRY_SCHEDULED'`) so two workers never retry the same attempt, and creates a new attempt row (new delivery id, attempt+1). The previous attempt row becomes `FAILED`.
6. Retry schedule (`WEBHOOK_RETRY_SCHEDULE`, default `0,30,120,600,1800`): delay before attempt N+1 is entry N, with +/-10% jitter, raised to `Retry-After` when present. Five attempts, then dead letter. Admin retry sets the latest attempt to retry immediately.

Execution is independent of delivery: events are written locally and delivered later, so subscriber failure never blocks AI execution or claims (FR-17).

## 3. Sequence: execution and claim

```
Dev -> API: POST /tasks              -> task.created
Dev -> API: POST /tasks/{id}/execute -> snapshot.baseline.created, execution.started   (202)
  background: wait; usage_record; execution.completed|failed ; then snapshot.post.created
Dev -> API: POST /claims             -> claim.submitted
Dev -> API: POST /claims/{id}/evaluate  -> evaluation.completed  (reads both snapshots)
Admin-> API: POST /claims/{id}/adjudicate -> claim.adjudicated
Admin-> API: POST /claims/{id}/settle     -> claim.settled  (policy limit, reserve)
every event -> outbox -> RabbitMQ -> worker -> subscribers
```

## 4. Data model

SQLAlchemy models in `backend/app/models/entities.py`; Alembic migration `0001`. Primary keys are prefixed random ids (`task_`, `evt_`, ...).

* Required tables: `developers`, `projects`, `tasks`, `executions`, `snapshots`, `usage_records`, `claims`, `evaluations`, `settlements`, `webhook_subscriptions`, `event_records`, `webhook_deliveries`, `outbox_events`.
* Added: `webhook_secrets` (encrypted secrets, referenced by `secret_reference`), `reserve_accounts` (mock reserve).
* `processed_events` lives in the **receiver's** own store, because deduplication is the subscriber's responsibility, not the platform's.
* Constraints: unique claim per execution, unique settlement per claim, unique evaluation per claim, unique snapshot per (execution, type), unique delivery per (event, subscription, attempt), unique outbox row per event; indexes on status/retry columns and owner ids.
* Subscriptions and events carry `developer_id`: a developer only receives events for their own tasks and can only see and change their own subscriptions.

## 5. Security

| Control | Implementation |
|---|---|
| API auth | `X-API-Key`; developer keys stored as SHA-256 hashes; admin key from environment, compared in constant time |
| Signing | `HMAC-SHA256(secret, timestamp + "." + raw_body)`, header `X-ST-Signature: v1=<hex>`; see EVENT_CATALOGUE |
| Verification | receiver reads raw body, checks 300 s tolerance, constant-time compare, dedups on event id |
| Secrets | generated (`whsec_` + 256-bit urlsafe); Fernet-encrypted at rest; returned once on create/rotate; never in list/detail responses or logs |
| SSRF | `security/endpoint_validation.py`: http(s) only, no URL credentials; production = https + public IPs only (all resolved addresses checked); localhost/private hosts only via `ALLOW_LOCALHOST_WEBHOOKS` (dev) with `DEV_ALLOWED_HOSTS`; revalidated with fresh DNS on every attempt; redirects never followed; 5 s timeout; response bodies capped at 2 KB |
| Payload minimisation | per-event Pydantic models forbid extra fields; no prompts, files or snapshots |
| Idempotency | event id stable across retries; delivery id per attempt; claim per execution; settlement per claim; receiver dedup |
| Observability | JSON logs with correlation id (`X-Correlation-ID`), delivery table, receiver log |

## 6. Deployment

Docker Compose: `postgres`, `rabbitmq`, `api` (runs `alembic upgrade head`, seeds the demo developer and mock reserve), `publisher`, `worker`, `receiver`, `frontend` (nginx). One backend image, three commands. Health checks gate startup (`postgres`/`rabbitmq` healthy -> `api` ready -> workers). Lite mode (`RUN_MODE=lite`) runs SQLite and an in-process queue inside the API process.

## 7. Assumptions

* Mock reserve 10,000 demo credits, per-claim limit 1,000, rate 5 credits per 1k tokens (all configurable) stand in for undecided policy.
* Evaluation rules: missing baseline/post evidence -> insufficient; failed execution -> eligible for assessment; completed execution with more failing tests than baseline -> eligible; otherwise not eligible. They illustrate the baseline-aware regression idea only.
* A failed execution still gets a (unchanged) post-change snapshot so it can be claimed.
* Event ordering across different event types is by `occurred_at`; queue delivery is not strictly ordered.
* A single receiver instance keeps one secret per subscription id.

## 8. Known limitations

* Simulation only: no LLM, real diff, tests, sandbox or payments.
* Lite mode queue is in-memory and not durable; use full mode to demonstrate durability.
* PostgreSQL and RabbitMQ paths were written to the same code as the tested SQLite/in-memory paths, but only SQLite/in-memory were executed in the development environment where Docker was unavailable; run the real-broker test and `docker compose up` to confirm in your environment.
* DNS rebinding is mitigated by re-resolving before each send, not by pinning the connection to the validated IP.
* Single-replica design for the retry poller assumptions beyond atomic row claims has not been load tested.
* Authentication is a prototype API key scheme (no users, rotation or rate limiting).
* The dashboard polls every 3 seconds and has no pagination.
