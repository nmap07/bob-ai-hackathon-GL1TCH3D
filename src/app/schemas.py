from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

AgentStatus = Literal["queued", "running", "completed", "completed_with_warnings", "failed", "not_applicable"]
ReviewStatus = Literal["unreviewed", "accepted", "rejected"]

class Artifact(BaseModel):
    artifact_id: str
    path: str
    type: str
    size_bytes: int
    sha256: str
    sha512: str | None = None
    parent_artifact_id: str | None = None
    read_only: bool = False

class Observation(BaseModel):
    observation_id: str
    agent_id: str
    agent_version: str
    type: str
    statement: str
    location: dict[str, Any] = Field(default_factory=dict)
    measurement: dict[str, Any] = Field(default_factory=dict)
    basis: list[str] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    not_tested: list[str] = Field(default_factory=list)
    calibrated: bool = False
    # Filled by the engine after the agent returns.
    derivative_id: str | None = None
    independence_group: str | None = None
    baseline: dict[str, Any] = Field(default_factory=dict)
    source: Literal["tool", "bob", "officer"] = "tool"
    review_status: ReviewStatus = "unreviewed"
    reviewed_by: str | None = None
    reviewed_utc: str | None = None
    review_reason: str | None = None

class AgentRun(BaseModel):
    agent_id: str
    version: str
    status: AgentStatus = "queued"
    run_id: str | None = None
    started_utc: str | None = None
    ended_utc: str | None = None
    duration_ms: int | None = None
    observation_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    envelope_path: str | None = None
    envelope_sha256: str | None = None

class Hypothesis(BaseModel):
    id: str
    label: str
    description: str
    support_observation_ids: list[str] = Field(default_factory=list)
    contradiction_observation_ids: list[str] = Field(default_factory=list)
    uninformative_observation_ids: list[str] = Field(default_factory=list)

class IntakeDetails(BaseModel):
    """Preservation-first intake fields (plan §4.3, C18). All optional."""
    officer_id: str | None = None
    officer_name: str | None = None
    how_received: str | None = None
    platform: str | None = None
    source_url: str | None = None
    sender_id: str | None = None
    received_at: str | None = None
    seizure_memo_ref: str | None = None
    device_details: str | None = None
    notes: str | None = None

class CaseState(BaseModel):
    case_id: str
    evidence_id: str
    filename: str
    media_type: str
    status: str = "created"
    stage: str = "intake"
    created_utc: str
    updated_utc: str
    source_description: str | None = None
    pipeline_run_id: str | None = None
    original: Artifact
    intake: IntakeDetails = Field(default_factory=IntakeDetails)
    baseline_profile: str = "builtin-default"
    agent_runs: dict[str, AgentRun] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[dict[str, Any]] = Field(default_factory=list)
    collected_evidence: dict[str, str] = Field(default_factory=dict)
    challenges: list[dict[str, Any]] = Field(default_factory=list)
    ach: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    triage: dict[str, Any] = Field(default_factory=dict)
    bob: dict[str, Any] = Field(default_factory=dict)
    legal: dict[str, Any] = Field(default_factory=dict)
    brief: dict[str, Any] = Field(default_factory=dict)
    analyst_assessment: dict[str, Any] = Field(default_factory=dict)
    reports: dict[str, str] = Field(default_factory=dict)
    ledger: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    human_review: dict[str, Any] = Field(default_factory=dict)
    signoffs: list[dict[str, Any]] = Field(default_factory=list)
    sealed: bool = False

class ReviewRequest(BaseModel):
    reviewer: str = "investigator"
    observation_id: str
    status: ReviewStatus
    reason: str = ""

class BulkReviewRequest(BaseModel):
    reviewer: str = "investigator"
    observation_ids: list[str]
    status: ReviewStatus
    reason: str = ""

class OfficerObservationRequest(BaseModel):
    """A human observation entered as a first-class finding (plan §7.2, source=officer)."""
    reviewer: str
    type: str
    statement: str
    location: dict[str, Any] = Field(default_factory=dict)
    alternative_explanations: list[str] = Field(default_factory=list)

class ACHEditRequest(BaseModel):
    editor: str = "analyst"
    group_id: str
    hypothesis_id: str
    value: Literal["C", "I", "N"]
    reason: str = ""

class ACHAcceptRequest(BaseModel):
    analyst: str

class EvidenceStatusRequest(BaseModel):
    officer: str = "investigator"
    item: str
    status: Literal["collected", "unavailable", "not_applicable", "missing"]

class LegalRequest(BaseModel):
    officer: str
    facts: dict[str, Any] = Field(default_factory=dict)
    confirmed_circumstances: list[str] | None = None

class VerifyRequest(BaseModel):
    text: str

class AnalystAssessmentRequest(BaseModel):
    analyst: str
    text: str

class BobPasteRequest(BaseModel):
    reply: str
    officer: str = "investigator"

class SignoffRequest(BaseModel):
    reviewer: str = "investigator"
    role: Literal["officer", "supervisor"] = "officer"
    statement: str
