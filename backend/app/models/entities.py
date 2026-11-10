from datetime import datetime

from sqlalchemy import (JSON, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime
from app.ids import utcnow


def ts_col(**kw):
    return mapped_column(UTCDateTime, default=utcnow, **kw)


class Developer(Base):
    __tablename__ = "developers"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = ts_col()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    developer_id: Mapped[str] = mapped_column(ForeignKey("developers.id"), index=True)
    created_at: Mapped[datetime] = ts_col()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    developer_id: Mapped[str] = mapped_column(ForeignKey("developers.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="CREATED", index=True)
    created_at: Mapped[datetime] = ts_col()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Execution(Base):
    __tablename__ = "executions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # RUNNING | COMPLETED | FAILED
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = ts_col()
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # simulation switches (mock)


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("execution_id", "snapshot_type", name="uq_snapshot_exec_type"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(20))  # BASELINE | POST_CHANGE
    project_state: Mapped[dict] = mapped_column(JSON)  # MOCK project state
    change_summary: Mapped[dict] = mapped_column(JSON)  # MOCK diff data
    evidence_ref: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = ts_col()


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), unique=True)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = ts_col()


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("execution_id", name="uq_claim_execution"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"))
    developer_id: Mapped[str] = mapped_column(ForeignKey("developers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    claim_reason: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = ts_col()
    adjudicated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    adjudication_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    adjudication_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts_col()
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), unique=True)
    settlement_status: Mapped[str] = mapped_column(String(30))
    calculated_credit: Mapped[float] = mapped_column(Float, default=0)
    eligible_credit: Mapped[float] = mapped_column(Float, default=0)
    reserve_before: Mapped[float] = mapped_column(Float)
    reserve_after: Mapped[float] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts_col()


class ReserveAccount(Base):
    """MOCK reserve pool (demo data, not a real financial account)."""
    __tablename__ = "reserve_accounts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    balance: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class WebhookSecret(Base):
    __tablename__ = "webhook_secrets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = ts_col()


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    developer_id: Mapped[str] = mapped_column(ForeignKey("developers.id"), index=True)
    subscriber_name: Mapped[str] = mapped_column(String(200))
    endpoint_url: Mapped[str] = mapped_column(String(1000))
    secret_reference: Mapped[str] = mapped_column(ForeignKey("webhook_secrets.id"))
    event_types: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = ts_col()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class EventRecord(Base):
    __tablename__ = "event_records"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # event_id
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    schema_version: Mapped[str] = mapped_column(String(10))
    developer_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = ts_col()
    publication_status: Mapped[str] = mapped_column(String(20), default="PENDING")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_status_created", "publication_status", "created_at"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("event_records.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    publication_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime] = ts_col()
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookDelivery(Base):
    """One row per delivery ATTEMPT (each attempt has its own delivery id)."""
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "subscription_id", "attempt_number", name="uq_delivery_attempt"),
        Index("ix_delivery_status_retry", "delivery_status", "next_retry_at"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("event_records.id"), index=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("webhook_subscriptions.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    delivery_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = ts_col()
