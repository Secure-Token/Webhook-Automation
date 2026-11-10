from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Claim, Evaluation, Execution, EventRecord, ReserveAccount, Settlement, Task,
                        WebhookDelivery)
from app.security.authentication import Principal, get_db, get_principal

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def _count(db, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/stats")
def stats(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    dev = None if p.is_admin else p.developer_id
    t_scope = [Task.developer_id == dev] if dev else []
    ex_scope = [Execution.task_id.in_(select(Task.id).where(*t_scope))] if dev else []
    ev_scope = [EventRecord.developer_id == dev, EventRecord.event_type != "webhook.test"] if dev \
        else [EventRecord.event_type != "webhook.test"]
    cl_scope = [Claim.developer_id == dev] if dev else []
    d_scope = [WebhookDelivery.event_id.in_(select(EventRecord.id).where(EventRecord.developer_id == dev))] if dev else []
    tokens = db.execute(select(func.coalesce(func.sum(Execution.input_tokens), 0),
                               func.coalesce(func.sum(Execution.output_tokens), 0)).where(*ex_scope)).one()
    reserve = db.get(ReserveAccount, "default")
    claim_ids = select(Claim.id).where(*cl_scope)
    return {
        "demo_data_notice": "Execution, evaluation, settlement and reserve values are SIMULATED demo data.",
        "tasks": _count(db, Task, *t_scope),
        "executions_running": _count(db, Execution, Execution.status == "RUNNING", *ex_scope),
        "executions_completed": _count(db, Execution, Execution.status == "COMPLETED", *ex_scope),
        "executions_failed": _count(db, Execution, Execution.status == "FAILED", *ex_scope),
        "tokens_input": tokens[0], "tokens_output": tokens[1], "tokens_total": tokens[0] + tokens[1],
        "events": _count(db, EventRecord, *ev_scope),
        "events_unpublished": _count(db, EventRecord, EventRecord.publication_status == "PENDING", *ev_scope),
        "deliveries_succeeded": _count(db, WebhookDelivery, WebhookDelivery.delivery_status == "SUCCEEDED", *d_scope),
        "deliveries_failed": _count(db, WebhookDelivery, WebhookDelivery.delivery_status.in_(("FAILED", "DEAD_LETTER")), *d_scope),
        "deliveries_pending_retry": _count(db, WebhookDelivery, WebhookDelivery.delivery_status == "RETRY_SCHEDULED", *d_scope),
        "claims_submitted": _count(db, Claim, *cl_scope),
        "evaluations_completed": _count(db, Evaluation, Evaluation.status == "COMPLETED", Evaluation.claim_id.in_(claim_ids)),
        "settlements_processed": _count(db, Settlement, Settlement.settlement_status.in_(("SETTLED", "PARTIALLY_SETTLED")), Settlement.claim_id.in_(claim_ids)),
        "reserve_balance_demo": reserve.balance if reserve else None,
    }
