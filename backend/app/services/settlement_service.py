"""Settlement SIMULATION. All amounts are DEMO DATA, not real money or insurance payments.

Credit = tokens/1000 * rate, capped by the per-claim policy limit, then by the reserve balance
(partial settlement). Only APPROVED claims settle; settlement is unique per claim.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ids import new_id
from app.models import Claim, Execution, ReserveAccount, Settlement
from app.services import event_service

RESERVE_ID = "default"


def calculate_credit(total_tokens: int, rate_per_1k: float, policy_limit: float, reserve: float) -> dict:
    calculated = round(total_tokens / 1000 * rate_per_1k, 2)
    after_policy = min(calculated, policy_limit)
    payable = round(max(0.0, min(after_policy, reserve)), 2)
    if payable <= 0:
        status = "DEFERRED_NO_RESERVE"
    elif payable < calculated:
        status = "PARTIALLY_SETTLED"
    else:
        status = "SETTLED"
    return {"calculated_credit": calculated, "policy_capped_credit": after_policy,
            "eligible_credit": payable, "settlement_status": status}


def get_reserve(db: Session) -> ReserveAccount:
    q = select(ReserveAccount).where(ReserveAccount.id == RESERVE_ID).with_for_update()
    acct = db.scalar(q)
    if acct is None:
        acct = ReserveAccount(id=RESERVE_ID, balance=get_settings().reserve_initial_balance)
        db.add(acct)
        db.flush()
    return acct


def settle_claim(db: Session, claim: Claim):
    """Returns (settlement, created)."""
    existing = db.scalar(select(Settlement).where(Settlement.claim_id == claim.id))
    if existing and existing.settlement_status != "DEFERRED_NO_RESERVE":
        return existing, False  # idempotent: repeated calls / webhook replays never double-settle
    if claim.status != "APPROVED":
        raise HTTPException(409, f"Only APPROVED claims can be settled (status: {claim.status})")
    s = get_settings()
    ex = db.get(Execution, claim.execution_id)
    reserve = get_reserve(db)
    before = reserve.balance
    calc = calculate_credit(ex.input_tokens + ex.output_tokens, s.credit_rate_per_1k_tokens,
                            s.policy_limit_per_claim, before)
    reserve.balance = round(before - calc["eligible_credit"], 2)
    details = {"demo_data": True, "tokens_billed": ex.input_tokens + ex.output_tokens,
               "rate_per_1k_tokens": s.credit_rate_per_1k_tokens, "policy_limit": s.policy_limit_per_claim,
               "policy_capped_credit": calc["policy_capped_credit"]}
    st = existing or Settlement(id=new_id("stl"), claim_id=claim.id, reserve_before=before, reserve_after=before)
    st.settlement_status, st.calculated_credit = calc["settlement_status"], calc["calculated_credit"]
    st.eligible_credit, st.reserve_before, st.reserve_after, st.details = (
        calc["eligible_credit"], before, reserve.balance, details)
    db.add(st)
    db.flush()
    if st.settlement_status != "DEFERRED_NO_RESERVE":
        claim.status = "SETTLED"
    event_service.emit(db, "claim.settled", {
        "settlement_id": st.id, "settlement_status": st.settlement_status,
        "eligible_credit": st.eligible_credit, "calculated_credit": st.calculated_credit},
        developer_id=claim.developer_id, task_id=claim.task_id, execution_id=claim.execution_id,
        claim_id=claim.id)
    db.commit()
    return st, True
