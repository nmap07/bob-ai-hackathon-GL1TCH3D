
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

AgentStatus = Literal["queued", "running", "completed", "completed_with_warnings", "failed", "not_applicable"]

class Artifact(BaseModel):
    artifact_id: str
    path: str
    type: str
    size_bytes: int
    sha256: str
    sha512: str | None = None
    parent_artifact_id: str | None = None

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
    calibrated: bool = False
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"

class AgentRun(BaseModel):
    agent_id: str
    version: str
    status: AgentStatus = "queued"
    started_utc: str | None = None
    ended_utc: str | None = None
    duration_ms: int | None = None
    observation_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

class Hypothesis(BaseModel):
    id: str
    label: str
    description: str
    support_observation_ids: list[str] = Field(default_factory=list)
    contradiction_observation_ids: list[str] = Field(default_factory=list)
    uninformative_observation_ids: list[str] = Field(default_factory=list)

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
    original: Artifact
    agent_runs: dict[str, AgentRun] = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[dict[str, Any]] = Field(default_factory=list)
    bob: dict[str, Any] = Field(default_factory=dict)
    legal: dict[str, Any] = Field(default_factory=dict)
    reports: dict[str, str] = Field(default_factory=dict)
    ledger: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    human_review: dict[str, Any] = Field(default_factory=dict)

class BobRequest(BaseModel):
    mode: str
    payload: dict[str, Any]

class ReviewRequest(BaseModel):
    reviewer: str = "investigator"
    observation_id: str
    status: Literal["accepted", "rejected", "unreviewed"]
    reason: str = ""

class SignoffRequest(BaseModel):
    reviewer: str = "investigator"
    statement: str
