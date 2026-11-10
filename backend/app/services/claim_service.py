"""Claims: submission, evaluation (SIMULATED), adjudication.

Eligibility (evaluation + adjudication) and settlement are separate decisions.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id, utcnow
from app.models import Claim, Evaluation, Execution, Snapshot, Task
from app.security.authentication import Principal
from app.services import event_service

ELIGIBLE = "ELIGIBLE_FOR_ASSESSMENT"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def get_claim_for(db: Session, principal: Principal, claim_id: str) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None or (not principal.is_admin and claim.developer_id != principal.developer_id):
        raise HTTPException(404, "Claim not found")
    return claim


def submit_claim(db: Session, principal: Principal, task: Task, execution_id: str | None, reason: str):
    """Returns (claim, created). Idempotent per execution."""
    q = select(Execution).where(Execution.task_id == task.id)
    if execution_id:
        q = q.where(Execution.id == execution_id)
    ex = db.scalars(q.order_by(Execution.started_at.desc())).first()
    if ex is None:
        raise HTTPException(404, "No execution found for this task")
    if ex.status == "RUNNING":
        raise HTTPException(409, "Execution is still running")
    existing = db.scalar(select(Claim).where(Claim.execution_id == ex.id))
    if existing:
        return existing, False
    claim = Claim(id=new_id("claim"), task_id=task.id, execution_id=ex.id, developer_id=task.developer_id,
                  status="SUBMITTED", claim_reason=reason)
    db.add(claim)
    db.flush()
    event_service.emit(db, "claim.submitted", {"status": claim.status}, developer_id=task.developer_id,
                       task_id=task.id, execution_id=ex.id, claim_id=claim.id)
    db.commit()
    return claim, True


def evaluate_claim(db: Session, claim: Claim) -> Evaluation:
    """SIMULATED evaluation over stored (mock) evidence. Not a real code-quality judge."""
    existing = db.scalar(select(Evaluation).where(Evaluation.claim_id == claim.id))
    if existing and existing.status == "COMPLETED":
        return existing
    ex = db.get(Execution, claim.execution_id)
    snaps = {s.snapshot_type: s for s in db.scalars(select(Snapshot).where(Snapshot.execution_id == ex.id))}
    base, post = snaps.get("BASELINE"), snaps.get("POST_CHANGE")

    checks = []
    evidence_complete = base is not None and post is not None
    checks.append({"check": "baseline_snapshot_present", "passed": base is not None})
    checks.append({"check": "post_change_snapshot_present", "passed": post is not None})
    checks.append({"check": "usage_recorded", "passed": ex.input_tokens + ex.output_tokens > 0})

    if not evidence_complete:
        result, summary = INSUFFICIENT, "Required baseline/post-change evidence is missing."
    elif ex.status == "FAILED":
        result, summary = ELIGIBLE, "Execution failed after token usage was billed."
        checks.append({"check": "execution_failed", "passed": True})
    else:
        bt, pt = base.project_state["tests"], post.project_state["tests"]
        regression = pt["failed"] > bt["failed"]
        checks.append({"check": "baseline_aware_regression", "passed": not regression,
                       "detail": {"baseline_failed": bt["failed"], "post_failed": pt["failed"]}})
        if regression:
            result, summary = ELIGIBLE, "Tests passing at baseline fail after the change (mock regression)."
        else:
            result, summary = NOT_ELIGIBLE, "No failure attributable to the AI change was found in mock evidence."

    report = {"simulated": True, "disclaimer": "Simulated evaluation over mock evidence; not a real quality judge.",
              "summary": summary, "evidence_complete": evidence_complete, "checks": checks,
              "baseline_snapshot": base.id if base else None, "post_snapshot": post.id if post else None}
    ev = existing or Evaluation(id=new_id("eval"), claim_id=claim.id, status="RUNNING")
    ev.status, ev.result, ev.report, ev.completed_at = "COMPLETED", result, report, utcnow()
    db.add(ev)
    claim.status = "EVALUATED"
    db.flush()
    event_service.emit(db, "evaluation.completed",
                       {"evaluation_id": ev.id, "result": result, "evidence_complete": evidence_complete},
                       developer_id=claim.developer_id, task_id=claim.task_id, execution_id=claim.execution_id,
                       claim_id=claim.id)
    db.commit()
    return ev


DECISIONS = {"APPROVED": "APPROVED", "REJECTED": "REJECTED", "MANUAL_REVIEW": "MANUAL_REVIEW"}


def adjudicate_claim(db: Session, claim: Claim, decision: str, notes: str | None) -> Claim:
    if decision not in DECISIONS:
        raise HTTPException(422, f"decision must be one of {sorted(DECISIONS)}")
    if claim.status in ("APPROVED", "REJECTED", "MANUAL_REVIEW", "SETTLED"):
        if claim.adjudication_decision == decision:
            return claim  # idempotent repeat
        raise HTTPException(409, f"Claim already adjudicated ({claim.status})")
    ev = db.scalar(select(Evaluation).where(Evaluation.claim_id == claim.id))
    if claim.status != "EVALUATED" or ev is None:
        raise HTTPException(409, "Claim must be evaluated before adjudication")
    if decision == "APPROVED" and ev.result != ELIGIBLE:
        raise HTTPException(409, f"Cannot approve a claim whose evaluation result is {ev.result}")
    claim.status = DECISIONS[decision]
    claim.adjudication_decision, claim.adjudication_notes, claim.adjudicated_at = decision, notes, utcnow()
    event_service.emit(db, "claim.adjudicated",
                       {"decision": decision, "status": claim.status, "evaluation_result": ev.result},
                       developer_id=claim.developer_id, task_id=claim.task_id, execution_id=claim.execution_id,
                       claim_id=claim.id)
    db.commit()
    return claim
