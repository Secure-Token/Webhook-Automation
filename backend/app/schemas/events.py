"""Event envelope and event-specific data models (schema version 1.0).

Payloads carry identifiers and small facts only: never prompts, source files,
credentials or whole snapshots. Use the referenced records instead.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "1.0"

EVENT_TYPES = [
    "task.created",
    "snapshot.baseline.created",
    "execution.started",
    "execution.completed",
    "execution.failed",
    "snapshot.post.created",
    "claim.submitted",
    "evaluation.completed",
    "claim.adjudicated",
    "claim.settled",
]
# Diagnostic event sent only by the subscription "test" endpoint (not part of the catalogue).
TEST_EVENT_TYPE = "webhook.test"


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskCreatedData(_Data):
    status: str
    project_id: str


class SnapshotData(_Data):
    snapshot_id: str
    snapshot_type: Literal["BASELINE", "POST_CHANGE"]
    evidence_ref: str
    mock: bool = True


class ExecutionStartedData(_Data):
    status: str
    model: str
    provider: str
    simulated: bool = True


class ExecutionCompletedData(_Data):
    status: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    usage_record_id: str
    simulated: bool = True
    # Per the architecture notes: completion does NOT imply post-change evidence is captured.
    # Wait for snapshot.post.created for that.
    post_snapshot_captured: bool = False


class ExecutionFailedData(_Data):
    status: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    usage_record_id: str | None = None
    error_message: str
    simulated: bool = True


class ClaimSubmittedData(_Data):
    status: str


class EvaluationCompletedData(_Data):
    evaluation_id: str
    result: str
    evidence_complete: bool
    simulated: bool = True


class ClaimAdjudicatedData(_Data):
    decision: str
    status: str
    evaluation_result: str | None = None


class ClaimSettledData(_Data):
    settlement_id: str
    settlement_status: str
    eligible_credit: float
    calculated_credit: float
    simulated: bool = True
    demo_data: bool = True


class WebhookTestData(_Data):
    message: str = "Secure Tokens webhook test event"


DATA_MODELS: dict[str, type[BaseModel]] = {
    "task.created": TaskCreatedData,
    "snapshot.baseline.created": SnapshotData,
    "snapshot.post.created": SnapshotData,
    "execution.started": ExecutionStartedData,
    "execution.completed": ExecutionCompletedData,
    "execution.failed": ExecutionFailedData,
    "claim.submitted": ClaimSubmittedData,
    "evaluation.completed": EvaluationCompletedData,
    "claim.adjudicated": ClaimAdjudicatedData,
    "claim.settled": ClaimSettledData,
    TEST_EVENT_TYPE: WebhookTestData,
}


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    schema_version: str = SCHEMA_VERSION
    occurred_at: datetime
    task_id: str | None = None
    execution_id: str | None = None
    claim_id: str | None = None
    correlation_id: str | None = None
    data: dict
