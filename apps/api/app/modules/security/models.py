"""Security tables (database-schema §5; migration security_0001)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class SecuritySignal(Base):
    __tablename__ = "security_signals"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    base_points: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    multipliers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    device_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    is_minor_at_time: Mapped[bool] = mapped_column(Boolean, nullable=False)
    suppressed_by_decision_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)


class RiskRule(Base):
    __tablename__ = "risk_rules"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_key: Mapped[str] = mapped_column(Text, nullable=False)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class RiskRuleVersion(Base):
    __tablename__ = "risk_rule_versions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("risk_rules.id"))
    family: Mapped[str] = mapped_column(Text, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(Text, nullable=False)
    semver: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    effective_from: Mapped[datetime | None] = mapped_column(_TS)
    shadow_started_at: Mapped[datetime | None] = mapped_column(_TS)
    shadow_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    proposed_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(_TS)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    status_changed_at: Mapped[datetime | None] = mapped_column(_TS)
    status_changed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    status_change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class RiskEvaluation(Base):
    __tablename__ = "risk_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    evaluated_at: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(Text, nullable=False)
    feed_version: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    window: Mapped[dict[str, Any]] = mapped_column("window", JSONB, nullable=False)
    signals: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    subtotals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    repeat_multiplier: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default="1.00")
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    previous_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    level_before: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    level_after: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gates: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    restriction_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    case_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    explanation_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    is_minor_at_time: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class SecurityCase(Base):
    __tablename__ = "security_cases"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    case_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recommended_level: Mapped[int | None] = mapped_column(SmallInteger)
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="medium")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    opened_reason: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    is_high_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    high_risk_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    repeat_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    hc_rule: Mapped[str | None] = mapped_column(Text)
    sla_first_response_due: Mapped[datetime | None] = mapped_column(_TS)
    sla_decision_due: Mapped[datetime | None] = mapped_column(_TS)
    first_response_at: Mapped[datetime | None] = mapped_column(_TS)
    sla_alerted_at: Mapped[datetime | None] = mapped_column(_TS)
    escalated_at: Mapped[datetime | None] = mapped_column(_TS)
    panel_views: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    closed_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AccountRestriction(Base):
    __tablename__ = "account_restrictions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(_TS)
    deferred_until: Mapped[datetime | None] = mapped_column(_TS)
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    case_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("security_cases.id"))
    applied_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    hc_rule: Mapped[str | None] = mapped_column(Text)
    ruleset_version: Mapped[str | None] = mapped_column(Text)
    rule_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    reverify_device_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(_UUID), nullable=False, server_default="{}"
    )
    lift_pending_at: Mapped[datetime | None] = mapped_column(_TS)
    ended_at: Mapped[datetime | None] = mapped_column(_TS)
    ended_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    end_reason: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class UnblockRequest(Base):
    __tablename__ = "unblock_requests"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    case_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("security_cases.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    restriction_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    closure_reason: Mapped[str | None] = mapped_column(Text)
    state_changed_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    what_happened: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    explanation: Mapped[str | None] = mapped_column(Text)
    recognised_device_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(_UUID), nullable=False, server_default="{}"
    )
    unrecognised_device_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(_UUID), nullable=False, server_default="{}"
    )
    lab_location_text: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    preferred_contact: Mapped[str | None] = mapped_column(Text)
    declaration_at: Mapped[datetime | None] = mapped_column(_TS)
    guardian_assisted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_second_level_appeal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    appeal_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    submitted_at: Mapped[datetime | None] = mapped_column(_TS)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    info_requested_at: Mapped[datetime | None] = mapped_column(_TS)
    info_requested_due: Mapped[datetime | None] = mapped_column(_TS)
    escalated_at: Mapped[datetime | None] = mapped_column(_TS)
    requires_second_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    decided_at: Mapped[datetime | None] = mapped_column(_TS)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    timeline: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CaseNote(Base):
    __tablename__ = "case_notes"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("security_cases.id"), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="internal")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CaseDecision(Base):
    __tablename__ = "case_decisions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("security_cases.id"), nullable=False)
    unblock_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    resulting_level: Mapped[int | None] = mapped_column(SmallInteger)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    student_summary: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    extension_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    false_positive_rule_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    decided_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    requires_second_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    approved_at: Mapped[datetime | None] = mapped_column(_TS)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class SecurityIncident(Base):
    __tablename__ = "security_incidents"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    incident_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="detected")
    detected_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    is_personal_data_breach: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    certin_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    certin_due_at: Mapped[datetime | None] = mapped_column(_TS)
    certin_reported_at: Mapped[datetime | None] = mapped_column(_TS)
    dpb_intimation_due_at: Mapped[datetime | None] = mapped_column(_TS)
    dpb_intimated_at: Mapped[datetime | None] = mapped_column(_TS)
    dpb_report_due_at: Mapped[datetime | None] = mapped_column(_TS)
    dpb_reported_at: Mapped[datetime | None] = mapped_column(_TS)
    principals_notified_at: Mapped[datetime | None] = mapped_column(_TS)
    affected_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    timeline: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    owner_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    closed_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class SecurityUserState(Base):
    __tablename__ = "security_user_state"

    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), primary_key=True)
    sharing_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    takeover_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    sharing_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    l2_issued_at: Mapped[datetime | None] = mapped_column(_TS)
    l2_passed_at: Mapped[datetime | None] = mapped_column(_TS)
    step_up_required_since: Mapped[datetime | None] = mapped_column(_TS)
    step_up_cleared_at: Mapped[datetime | None] = mapped_column(_TS)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class SecurityCounter(Base):
    __tablename__ = "security_counters"

    counter_key: Mapped[str] = mapped_column(Text, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class SecurityNotice(Base):
    __tablename__ = "security_notices"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    event_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(_TS)
    disowned_at: Mapped[datetime | None] = mapped_column(_TS)


class SecurityReportExport(Base):
    __tablename__ = "security_report_exports"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    report_key: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    include_per_user_rows: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    contains_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    row_count: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str | None] = mapped_column(Text)
    watermark: Mapped[str | None] = mapped_column(Text)
    download_expires_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class SecurityBulkLift(Base):
    __tablename__ = "security_bulk_lifts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    selector: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    extension_credit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    requested_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    matched_restriction_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(_UUID), nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
