# Functional Requirements Document: Webhook Automation Prototype

Status: prototype requirements derived from the Secure Tokens handover (`docs/Secure_Tokens_Project_Context_for_Claude.md`). The webhook layer is a **proposal**; simulated parts are marked.

## 1. Actors

| Actor | Role |
|---|---|
| Developer | creates tasks, runs executions, raises claims, registers webhooks |
| Operator / admin | adjudicates and settles claims, retries deliveries, inspects payloads |
| Webhook subscriber | external system receiving signed events (sample receiver) |
| Simulated AI execution service | stands in for the coding agent (no real LLM) |

## 2. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Authenticate API calls with an API key; admin operations need the admin key. |
| FR-2 | Create tasks tied to a developer and project; track status CREATED/RUNNING/COMPLETED/FAILED. |
| FR-3 | Capture a mock baseline snapshot before execution and a mock post-change snapshot after it. |
| FR-4 | Run a simulated execution (RUNNING then COMPLETED or FAILED), recording mock token usage. |
| FR-5 | Generate the ten catalogued events only when the underlying operation occurred, persisted atomically with it. |
| FR-6 | Publish events through a transactional outbox to RabbitMQ; broker failure must not lose events. |
| FR-7 | Let developers register, update, activate/deactivate, test and delete webhook subscriptions with event filters; generate a signing secret shown once. |
| FR-8 | Deliver events asynchronously as HMAC-SHA256 signed HTTP POSTs to matching active subscriptions. |
| FR-9 | Retry temporary failures with backoff, jitter and `Retry-After`; dead-letter exhausted deliveries; allow admin retry. |
| FR-10 | Record every delivery attempt (status, response code, summary, error, next retry). |
| FR-11 | Provide a sample receiver that verifies signatures and timestamps, deduplicates events and records outcomes. |
| FR-12 | Accept claims against a finished execution (idempotent per execution). |
| FR-13 | Run a simulated evaluation over stored evidence: eligible for assessment / not eligible / insufficient evidence. |
| FR-14 | Record adjudication (admin) as a separate decision from evaluation; refuse approval of non-eligible claims. |
| FR-15 | Simulate settlement from a mock reserve with a mock policy limit; partial settlement when capped; one settlement per claim. |
| FR-16 | Provide a dashboard for tasks, events, subscriptions, deliveries, retries, claims and settlements. |
| FR-17 | Subscriber unavailability must not block execution or the claim workflow. |

## 3. Workflows

1. **Execution**: create task (`task.created`) -> baseline snapshot (`snapshot.baseline.created`) -> start (`execution.started`) -> usage recorded -> `execution.completed` or `execution.failed` -> post-change snapshot (`snapshot.post.created`).
2. **Claim**: submit (`claim.submitted`) -> evaluate (`evaluation.completed`) -> adjudicate (`claim.adjudicated`) -> settle (`claim.settled`).
3. **Delivery**: event committed -> outbox -> RabbitMQ -> worker fan-out -> signed POST -> record -> retry or finish.

## 4. Business rules

* A webhook communicates that something happened; it neither evaluates code nor approves claims.
* Claim eligibility (evaluation + adjudication) and settlement are separate decisions. Settlement is bounded by the policy limit and reserve.
* Insufficient evidence never leads to automatic compensation.
* Completion events do not imply post-change evidence exists.
* A repeated request, queue redelivery or webhook replay must not create a duplicate claim, settlement or receiver-side processing.
* All simulated components, credits and the reserve are labelled demo data. Credits are not provider refunds or money.
* Payloads exclude prompts, source files, credentials and full snapshots.

Unresolved by the source material and therefore **mocked**, not decided: scoring algorithm, eligibility and compensation formulas, reserve funding. The mock formula is `tokens/1000 * rate`, capped by the per-claim limit then the reserve.

## 5. Acceptance criteria

| Criterion | Verified by |
|---|---|
| Ten events generated at the right stages, in order | `test_execution_flow_events_snapshots_and_usage`, scenario A |
| Signed delivery verified by receiver | `test_events_delivered_signed_and_recorded` |
| Outage then recovery without blocking execution | `test_subscriber_down_...`, scenario B |
| Retry exhaustion dead-letters; admin retry works | `test_exhausted_retries_...` |
| Invalid signature / stale timestamp rejected | `test_receiver_rejects_*`, scenario C |
| Duplicate event not reprocessed | `test_receiver_dedups_same_event`, scenario D |
| Task-to-settlement flow, idempotent settlement | `test_full_workflow_task_to_settlement`, scenario E |
| Insufficient evidence cannot settle | `test_insufficient_evidence_never_settles`, scenario F |
| Broker outage loses no events | `test_outbox_survives_broker_outage` |
| Secrets never leak; SSRF rules enforced | `tests/test_security.py` |
