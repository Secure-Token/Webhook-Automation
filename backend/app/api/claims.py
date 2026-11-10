from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, Evaluation, Settlement
from app.schemas.api import (AdjudicateRequest, ClaimCreate, ClaimOut, EvaluationOut, SettlementOut)
from app.security.authentication import (Principal, get_db, get_principal, require_admin, require_developer)
from app.services import claim_service, settlement_service, task_service

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


def _claim_out(db: Session, c: Claim) -> ClaimOut:
    out = ClaimOut.model_validate(c)
    ev = db.scalar(select(Evaluation).where(Evaluation.claim_id == c.id))
    st = db.scalar(select(Settlement).where(Settlement.claim_id == c.id))
    out.evaluation_status = ev.status if ev else None
    out.evaluation_result = ev.result if ev else None
    out.settlement_status = st.settlement_status if st else None
    return out


@router.post("", response_model=ClaimOut, status_code=201)
def submit_claim(body: ClaimCreate, response: Response, p: Principal = Depends(require_developer),
                 db: Session = Depends(get_db)):
    task = task_service.get_task_for(db, p, body.task_id)
    claim, created = claim_service.submit_claim(db, p, task, body.execution_id, body.claim_reason)
    if not created:
        response.status_code = 200  # idempotent repeat
    return _claim_out(db, claim)


@router.get("", response_model=list[ClaimOut])
def list_claims(limit: int = 100, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(Claim).order_by(Claim.submitted_at.desc()).limit(min(limit, 500))
    if not p.is_admin:
        q = q.where(Claim.developer_id == p.developer_id)
    return [_claim_out(db, c) for c in db.scalars(q).all()]


@router.get("/{claim_id}")
def get_claim(claim_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    c = claim_service.get_claim_for(db, p, claim_id)
    ev = db.scalar(select(Evaluation).where(Evaluation.claim_id == c.id))
    st = db.scalar(select(Settlement).where(Settlement.claim_id == c.id))
    return {"claim": _claim_out(db, c),
            "evaluation": EvaluationOut.model_validate(ev) if ev else None,
            "settlement": SettlementOut.model_validate(st) if st else None}


@router.post("/{claim_id}/evaluate", response_model=EvaluationOut)
def evaluate(claim_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return claim_service.evaluate_claim(db, claim_service.get_claim_for(db, p, claim_id))


@router.post("/{claim_id}/adjudicate", response_model=ClaimOut)
def adjudicate(claim_id: str, body: AdjudicateRequest, p: Principal = Depends(require_admin),
               db: Session = Depends(get_db)):
    claim = claim_service.get_claim_for(db, p, claim_id)
    return _claim_out(db, claim_service.adjudicate_claim(db, claim, body.decision, body.notes))


@router.post("/{claim_id}/settle", response_model=SettlementOut)
def settle(claim_id: str, response: Response, p: Principal = Depends(require_admin),
           db: Session = Depends(get_db)):
    claim = claim_service.get_claim_for(db, p, claim_id)
    st, created = settlement_service.settle_claim(db, claim)
    response.status_code = 201 if created else 200
    return st
