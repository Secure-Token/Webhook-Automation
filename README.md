# Secure Tokens: Webhook Automation Prototype

A working demonstration of the **proposed webhook automation layer** for Secure Tokens: durable event creation, internal queueing, signed external webhook delivery with retries and idempotency, and an observable dashboard.

> **Scope and honesty notes.** This is **not** the full Secure Tokens platform. The webhook service and event manager are *proposed additions*, not finalized components. AI execution, project snapshots, evaluation, adjudication, settlement, the reserve and all credit values are **simulated demo data**. No real LLM, payment or insurance logic exists here. The REST routes and event names are prototype interfaces, not existing Secure Tokens contracts. See `docs/Secure_Tokens_Project_Context_for_Claude.md` for the source context.

Everything used is free and open source. No paid services, cloud accounts or API keys are needed.

## What it demonstrates

```
Developer -> API -> task -> baseline snapshot -> simulated execution -> token usage -> completed/failed
   -> event (same DB transaction as the change) -> outbox -> RabbitMQ -> delivery worker
   -> signed HTTP POST -> sample receiver verifies + deduplicates -> post-change snapshot
   -> claim -> evidence -> simulated evaluation -> adjudication -> mock settlement -> final events
```

Key properties: transactional outbox (no lost events if the broker is down), HMAC-SHA256 signatures with timestamp tolerance, SSRF-aware endpoint validation, retries with backoff/jitter/`Retry-After`, dead-letter state, per-attempt delivery IDs, receiver-side deduplication, idempotent claims and settlements, and subscriber outages that never block execution or claims.

## Architecture

| Component | Where |
|---|---|
| API gateway + services (tasks, execution, snapshots, claims, evaluation, settlement) | `backend/app` |
| Event Manager + outbox | `backend/app/services/event_service.py`, `workers/event_publisher.py` |
| Internal queue | RabbitMQ (`backend/app/broker.py`) |
| Webhook delivery service + retry poller | `backend/app/services/webhook_service.py`, `workers/webhook_worker.py` |
| Sample external subscriber | `receiver/` |
| Dashboard | `frontend/` (React + Vite) |

Stack: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, RabbitMQ, HTTPX, Pydantic, React/Vite, Docker Compose, Pytest.

Two run modes (`RUN_MODE`):

* **full**: PostgreSQL + RabbitMQ via Docker Compose (the intended architecture).
* **lite**: SQLite + in-process queue, no Docker. Same code; the API process also runs the publisher and delivery worker. The in-process queue is not durable.

## Prerequisites

* Full mode: Docker with Compose.
* Lite mode / tests: Python 3.11+ and Node 20+.

## Run with Docker (full mode)

```bash
cp .env.example .env            # defaults work for local demo
docker compose up --build -d
python scripts/seed_demo_data.py --webhook-host receiver   # registers the sample receiver subscription
```

| URL | What |
|---|---|
| http://localhost:5173 | Dashboard |
| http://localhost:8000/docs | Swagger / OpenAPI |
| http://localhost:9000/receiver/events | Sample receiver log |
| http://localhost:15672 | RabbitMQ management (guest/guest) |

Stop: `docker compose down` (add `-v` to wipe data).

Default demo keys (change in `.env`): developer `st_dev_demo_key`, admin `st_admin_dev_key`. Enter them in the dashboard header. Admin is required for adjudicate, settle and delivery retry.

## Run without Docker (lite mode)

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt         # Windows; use .venv/bin/pip on Linux/macOS
# terminal 1: receiver
cd receiver && ../.venv/Scripts/python -m uvicorn main:app --port 9000
# terminal 2: API (+ in-process workers)
cd backend && RUN_MODE=lite EXECUTION_DELAY_SECONDS=1 WEBHOOK_RETRY_SCHEDULE=0,3,5,8,10 ../.venv/Scripts/python -m uvicorn app.main:app --port 8000
# terminal 3: dashboard
cd frontend && npm install && npm run dev
```

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest -q
```

Unit, integration, security and end-to-end tests run on SQLite with an in-process queue (the receiver logic and HMAC verification are real). `tests/test_rabbitmq_integration.py` runs against a real broker and is skipped automatically when RabbitMQ is not reachable (start it with `docker compose up -d rabbitmq`).

## Demo

With the stack running: `python scripts/run_demo.py` (add `--webhook-host receiver` under Docker) runs scenarios A to F. Manual steps: `docs/DEMO_GUIDE.md`.

## Documentation

`docs/FRD.md` requirements · `docs/SSD.md` design · `docs/API.md` endpoints · `docs/EVENT_CATALOGUE.md` events and payloads · `docs/DEMO_GUIDE.md` scenarios.

## Known limitations

See the end of `docs/SSD.md`.
