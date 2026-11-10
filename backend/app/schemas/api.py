from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.events import EVENT_TYPES


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    description: str = Field(min_length=3, max_length=5000)
    project_id: str | None = None


class TaskOut(ORM):
    id: str
    project_id: str
    developer_id: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime


class ExecuteRequest(BaseModel):
    """Switches for the SIMULATED execution (mock behaviour only)."""
    simulate_failure: bool = False
    simulate_regression: bool = False
    simulate_missing_evidence: bool = False


class ExecutionOut(ORM):
    id: str
    task_id: str
    status: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None
    options: dict


class SnapshotOut(ORM):
    id: str
    task_id: str
    execution_id: str
    snapshot_type: str
    project_state: dict
    change_summary: dict
    evidence_ref: str
    created_at: datetime


class ClaimCreate(BaseModel):
    task_id: str
    execution_id: str | None = None
    claim_reason: str = Field(min_length=3, max_length=5000)


class AdjudicateRequest(BaseModel):
    decision: str
    notes: str | None = Field(default=None, max_length=2000)


class EvaluationOut(ORM):
    id: str
    claim_id: str
    status: str
    result: str | None
    report: dict
    created_at: datetime
    completed_at: datetime | None


class SettlementOut(ORM):
    id: str
    claim_id: str
    settlement_status: str
    calculated_credit: float
    eligible_credit: float
    reserve_before: float
    reserve_after: float
    details: dict
    created_at: datetime


class ClaimOut(ORM):
    id: str
    task_id: str
    execution_id: str
    status: str
    claim_reason: str
    submitted_at: datetime
    adjudicated_at: datetime | None
    adjudication_decision: str | None
    adjudication_notes: str | None
    evaluation_status: str | None = None
    evaluation_result: str | None = None
    settlement_status: str | None = None


def _check_event_types(v: list[str]) -> list[str]:
    if not v:
        raise ValueError("event_types must not be empty")
    bad = [e for e in v if e != "*" and e not in EVENT_TYPES]
    if bad:
        raise ValueError(f"Unknown event types: {bad}")
    return sorted(set(v))


class SubscriptionCreate(BaseModel):
    subscriber_name: str = Field(min_length=1, max_length=200)
    endpoint_url: str = Field(max_length=1000)
    event_types: list[str]

    @field_validator("event_types")
    @classmethod
    def _et(cls, v):
        return _check_event_types(v)


class SubscriptionUpdate(BaseModel):
    subscriber_name: str | None = Field(default=None, max_length=200)
    endpoint_url: str | None = Field(default=None, max_length=1000)
    event_types: list[str] | None = None
    status: str | None = None

    @field_validator("event_types")
    @classmethod
    def _et(cls, v):
        return _check_event_types(v) if v is not None else v

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in ("ACTIVE", "INACTIVE"):
            raise ValueError("status must be ACTIVE or INACTIVE")
        return v


class SubscriptionOut(ORM):
    """Never includes the signing secret."""
    id: str
    subscriber_name: str
    endpoint_url: str
    event_types: list[str]
    status: str
    secret_reference: str
    created_at: datetime
    updated_at: datetime


class SubscriptionCreated(SubscriptionOut):
    signing_secret: str  # shown ONCE


class EventSummary(ORM):
    id: str
    event_type: str
    schema_version: str
    task_id: str | None
    execution_id: str | None
    claim_id: str | None
    occurred_at: datetime
    publication_status: str


class EventDetail(EventSummary):
    payload: dict


class DeliveryOut(ORM):
    id: str
    event_id: str
    subscription_id: str
    attempt_number: int
    delivery_status: str
    response_code: int | None
    response_body_summary: str | None
    attempted_at: datetime | None
    next_retry_at: datetime | None
    error_message: str | None
    duration_ms: int | None
    created_at: datetime
    subscriber_name: str | None = None
    event_type: str | None = None
