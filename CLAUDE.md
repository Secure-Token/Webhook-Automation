# CLAUDE.md

Secure Tokens webhook automation prototype. Read `README.md` for run instructions and `docs/` (FRD, SSD, API, EVENT_CATALOGUE, DEMO_GUIDE) for the spec. This file records decisions, history and the reasoning behind them, so future sessions don't re-litigate them.

## Scope (do not overstate)
- This is a **prototype of a proposed webhook layer**, not the Secure Tokens platform. Event names and REST routes are prototype interfaces, not existing contracts.
- AI execution, snapshots, evaluation, adjudication, settlement, reserve and credit values are **simulated demo data**. Keep the `simulated` / `demo_data` flags and disclaimers in code and docs.
- Source context: `docs/Secure_Tokens_Project_Context_for_Claude.md` (original brief, 2026-11-07).
- **Latest source doc: `docs/Secure-Token-Technical-Audit-Report.pdf`** (added 2026-11-12, newest file in `docs/`, supersedes the brief where they differ). It audits the real Secure-Token (ST) gateway: Layers 1-2 (proxy, metering, policy, hash-chained audit) and team memory are built; sandbox runner, Q-score evaluation, double-entry ledger/reserve pool are only specified; claims tables/RPCs exist but are manual. Its section 9 states **no outgoing webhook dispatch or retry queue exists in ST today**, so this prototype is a proposal, not a mirror of existing behaviour. Evaluation/settlement/reserve here remain simulated. The PDF is untracked in git; the FRD/SSD/API/EVENT_CATALOGUE docs (2026-11-10) predate it and have not yet been reconciled against it.
- Everything must stay free/open source; no paid services or API keys.

## Layout
- `backend/app` FastAPI API, services, models, security, workers. `backend/tests` pytest.
- `receiver/` independent sample subscriber (stdlib sqlite, own copy of HMAC rules, so it behaves like a real external party).
- `frontend/` React + Vite dashboard. `scripts/` demo runners. `docker-compose.yml` full stack.

## Commands
- Tests: `cd backend && python -m pytest -q` (SQLite + in-process queue; RabbitMQ test auto-skips without a broker).
- Run modes via `RUN_MODE`: `full` (PostgreSQL + RabbitMQ) or `lite` (SQLite + in-memory queue, API process also runs publisher and delivery worker).

## Design decisions and why
| Decision | Why |
|---|---|
| **Transactional outbox**: event row + outbox row written in the same DB transaction as the business change; a publisher moves them to the broker | No lost events if the broker is down; events never describe uncommitted state. Delivery is therefore **at-least-once**, so consumers must deduplicate (the receiver does). |
| **Subscriber outages never block execution or claims** | A webhook means "subscriber was notified", never proof of business success. Delivery is decoupled via queue + worker. |
| **Every attempt is its own `WebhookDelivery` row with its own delivery ID**; a `RETRY_SCHEDULED` row becomes `FAILED` when its successor is created | Per-attempt audit trail and a clean atomic claim for retries. |
| **HMAC-SHA256 over `timestamp + "." + raw body`**, `X-ST-Signature: v1=<hex>`, timestamp tolerance, constant-time compare | Replay protection; signing the exact wire bytes (`canonical_body`: compact, sorted-key JSON) avoids re-serialisation mismatches. Receivers must verify the raw body. |
| **Secrets generated once, Fernet-encrypted at rest, never logged**; API keys stored as SHA-256 hashes | Standard secret hygiene even for a prototype. |
| **SSRF validation** at subscribe time and again at send time; no redirects followed; production requires https + public IPs; dev exception only for `DEV_ALLOWED_HOSTS` when `ALLOW_LOCALHOST_WEBHOOKS` is on | Block internal-network targets; re-resolving at send time mitigates DNS rebinding. |
| **Retry policy**: configurable schedule + jitter + `Retry-After`; 408/425/429/5xx temporary, other 4xx/3xx permanent; `DEAD_LETTER` after max attempts; manual retry endpoint (admin) | Distinguish transient from permanent failures; don't hammer broken endpoints. |
| **Idempotent claims (per execution) and settlements (per claim)** | Webhook replays and repeated API calls must never double-settle. |
| **Eligibility (evaluation + adjudication) and settlement are separate decisions**; only APPROVED claims settle; APPROVE requires an ELIGIBLE evaluation | Mirrors the intended business separation; settlement amount depends on policy cap and reserve, which can yield `PARTIALLY_SETTLED` / `DEFERRED_NO_RESERVE`. |
| **Two run modes (full / lite) sharing the same code** | Lite lets the prototype run and be tested with no Docker; full shows the intended architecture. |
| **Prototype API-key auth** (developer key vs admin key) | Enough to demonstrate tenant scoping and admin-only actions; real auth is out of scope. |

## History
1. `1f795b9` Initial commit.
2. `1c3e3cc` Added the full prototype (backend, outbox, RabbitMQ publisher, signed delivery with retries/dead-letter, receiver, dashboard, tests, Docker Compose, docs).
3. Review + fixes (session 2026-11-11, uncommitted at time of writing):
   - **Stuck `IN_PROGRESS` deliveries**: a worker crash after marking a row `IN_PROGRESS` left it orphaned forever. Added `recover_stale_in_progress` (called from `run_due_retries`), which atomically resets rows stale for > `3 * webhook_timeout_seconds + 30` s to `PENDING` and re-sends. Trade-off: at-least-once, possible duplicate send after a crash; receivers dedupe.
   - **Lost retry**: marking the old attempt `FAILED` and inserting the successor were two commits; a crash between lost the retry. Now one commit.
   - **Auth 500**: `hmac.compare_digest` on `str` raises `TypeError` for non-ASCII keys; now compares bytes, giving 401.
   - Added tests for all three. Suite: 45 passed, 1 skipped (RabbitMQ).

## Known gaps (reviewed, deliberately not fixed yet)
- DNS rebinding: validation re-resolves but httpx resolves again at connect; pinning the validated IP would close it.
- `settle_claim` checks for an existing settlement before taking the reserve row lock; verify a unique constraint on `settlements.claim_id` or lock first.
- Receiver is demo-only: CORS `*`, default admin token, unauthenticated `/receiver/events`.
- `matching_subscriptions` loads all active subscriptions and filters in Python.
- PostgreSQL/RabbitMQ paths were never executed in the original dev environment (no Docker); only SQLite/in-memory were. Confirm with `docker compose up` and the RabbitMQ test.
- No load testing; dashboard polls every 3 s with no pagination.

## Working conventions
- Don't present simulated results as real. Keep scope notes in docs honest.
- Add a test with each bug fix. Keep delivery code idempotent and safe to replay.
- Don't commit secrets; `.env.example` holds dev-only defaults.

## Session 2026-11-13 notes
- **Webhooks page default URL** is now `http://localhost:9000/...` (lite mode), overridable via `VITE_DEFAULT_WEBHOOK_URL` at build time. Previously it was hard-coded to the Docker hostname `receiver`, which caused every dashboard-created subscription to fail DNS (`getaddrinfo failed`) and dead-letter in lite mode. For Docker Compose, the frontend image build would need that variable set (not wired into `docker-compose.yml` yet).
- Presentation runs in **lite mode only** (no Docker). Local DB `backend/securetokens_lite.db` is gitignored; delete it and restart the API for a clean state, then run `python scripts/seed_demo_data.py`.
