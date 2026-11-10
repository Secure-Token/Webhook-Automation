"""Simulated AI execution service (NO real LLM is called).

start_execution(): synchronous, commits baseline snapshot + RUNNING execution + events.
run_simulation(): background work; sleeps, records mock token usage, completes or fails,
then captures the post-change snapshot (unless the "missing evidence" switch is set).
"""
import logging
import random
import time

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.ids import new_id, utcnow
from app.models import Execution, Task, UsageRecord
from app.services import event_service, snapshot_service

log = logging.getLogger(__name__)
MODEL, PROVIDER = "mock-model", "mock-provider"


def start_execution(db: Session, task: Task, options: dict) -> Execution:
    if task.status == "RUNNING":
        raise HTTPException(409, "Task already has a running execution")
    ex = Execution(id=new_id("exec"), task_id=task.id, status="RUNNING", model=MODEL, provider=PROVIDER,
                   options=options)
    db.add(ex)
    db.flush()
    snapshot_service.capture_baseline(db, task, ex)
    task.status = "RUNNING"
    event_service.emit(db, "execution.started",
                       {"status": "RUNNING", "model": MODEL, "provider": PROVIDER},
                       developer_id=task.developer_id, task_id=task.id, execution_id=ex.id)
    db.commit()
    return ex


def run_simulation(execution_id: str) -> None:
    """Background job. Uses its own session; never raises into the web request."""
    settings = get_settings()
    time.sleep(settings.execution_delay_seconds)
    db = SessionLocal()
    try:
        ex = db.get(Execution, execution_id)
        task = db.get(Task, ex.task_id)
        opts = ex.options or {}
        failed = bool(opts.get("simulate_failure"))
        in_tok = random.randint(800, 4000)
        out_tok = random.randint(200, 1500) if not failed else random.randint(20, 120)

        usage = UsageRecord(id=new_id("usage"), task_id=task.id, execution_id=ex.id, input_tokens=in_tok,
                            output_tokens=out_tok, model=ex.model, provider=ex.provider)
        db.add(usage)
        ex.input_tokens, ex.output_tokens, ex.completed_at = in_tok, out_tok, utcnow()
        if failed:
            ex.status, task.status = "FAILED", "FAILED"
            ex.error_message = "Simulated execution failure"
            event_service.emit(db, "execution.failed", {
                "status": "FAILED", "model": ex.model, "provider": ex.provider, "input_tokens": in_tok,
                "output_tokens": out_tok, "usage_record_id": usage.id, "error_message": ex.error_message},
                developer_id=task.developer_id, task_id=task.id, execution_id=ex.id)
        else:
            ex.status, task.status = "COMPLETED", "COMPLETED"
            event_service.emit(db, "execution.completed", {
                "status": "COMPLETED", "model": ex.model, "provider": ex.provider, "input_tokens": in_tok,
                "output_tokens": out_tok, "usage_record_id": usage.id},
                developer_id=task.developer_id, task_id=task.id, execution_id=ex.id)
        db.commit()

        # Separate step: evidence capture happens after the completion is recorded.
        if not opts.get("simulate_missing_evidence"):
            snapshot_service.capture_post_change(db, task, ex)
            db.commit()
        log.info("execution finished", extra={"ctx": {"execution_id": ex.id, "status": ex.status}})
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("simulated execution crashed")
        ex = db.get(Execution, execution_id)
        if ex and ex.status == "RUNNING":
            ex.status, ex.error_message, ex.completed_at = "FAILED", "Internal simulation error", utcnow()
            task = db.get(Task, ex.task_id)
            task.status = "FAILED"
            db.commit()
    finally:
        db.close()
