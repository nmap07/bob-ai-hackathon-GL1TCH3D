
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from app.engine import InvestigationEngine
from app.store import CaseStore
from app.schemas import CaseState

ROOT = Path(__file__).resolve().parent
STORE = CaseStore(ROOT / "cases")
ENGINE = InvestigationEngine(STORE)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("emafg-mcp")

mcp = MCPServer(
    "EMAFIG Forensic Control",
    instructions=(
        "Bounded forensic control tools for EMAFIG. "
        "Use the tools to inspect case state, start deterministic forensic analysis, "
        "review observations, verify the audit chain, and generate evidence packages. "
        "Never treat automated observations as a legal or final truth verdict."
    ),
    version="2.0.0",
)


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _case(case_id: str) -> CaseState:
    state = STORE.load(case_id)
    if state is None:
        raise ValueError(f"Unknown case_id: {case_id}")
    return state


@mcp.tool()
def list_cases() -> str:
    """List EMAFIG cases with status, media type, and investigation stage."""
    rows = []
    for c in STORE.list_cases():
        rows.append(
            {
                "case_id": c.case_id,
                "evidence_id": c.evidence_id,
                "filename": c.filename,
                "media_type": c.media_type,
                "status": c.status,
                "stage": c.stage,
                "observations": len(c.observations),
                "contradictions": len(c.contradictions),
                "updated_utc": c.updated_utc,
            }
        )
    return _json(rows)


@mcp.tool()
def get_case(case_id: str) -> str:
    """Return complete structured state for one EMAFIG case."""
    return _json(_case(case_id).model_dump())


@mcp.tool()
def get_agent_status(case_id: str) -> str:
    """Return every forensic agent's status, warnings, timings and observation count."""
    c = _case(case_id)
    return _json(
        {
            aid: {
                "status": run.status,
                "version": run.version,
                "started_utc": run.started_utc,
                "ended_utc": run.ended_utc,
                "duration_ms": run.duration_ms,
                "observation_count": len(run.observation_ids),
                "warnings": run.warnings,
                "error": run.error,
            }
            for aid, run in c.agent_runs.items()
        }
    )


@mcp.tool()
def get_observations(case_id: str) -> str:
    """Return structured forensic observations, including measurements and limitations."""
    c = _case(case_id)
    return _json([o.model_dump() for o in c.observations])


@mcp.tool()
def get_hypotheses(case_id: str) -> str:
    """Return competing hypotheses and supporting/contradicting observation IDs."""
    c = _case(case_id)
    return _json([h.model_dump() for h in c.hypotheses])


@mcp.tool()
def get_contradictions(case_id: str) -> str:
    """Return unresolved contradictions recorded by the reasoning pipeline."""
    c = _case(case_id)
    return _json(c.contradictions)


@mcp.tool()
def get_missing_evidence(case_id: str) -> str:
    """Return pipeline failures, warnings, and evidence gaps."""
    c = _case(case_id)
    return _json(c.missing_evidence)


@mcp.tool()
def verify_audit_ledger(case_id: str) -> str:
    """Verify the append-only hash chain for the case audit ledger."""
    return _json(STORE.ledger(case_id).verify())


@mcp.tool()
async def start_investigation(case_id: str) -> str:
    """Run the deterministic examiners and reasoning for a case that is still queued."""
    c = _case(case_id)
    if c.status != "queued":
        return _json({"status": c.status, "stage": c.stage, "message": "Case already analysed; use rerun_reasoning."})
    await ENGINE.run_analysis(case_id)
    c = _case(case_id)
    return _json({"status": c.status, "risk": c.risk.get("risk_score"), "band": c.risk.get("band")})


@mcp.tool()
async def rerun_reasoning(case_id: str) -> str:
    """Re-run Bob reasoning (ACH proposals, skeptic, triage estimate) over the current reviewed observations."""
    c = await ENGINE.rerun_reasoning(case_id)
    return _json({"ach_assessor": c.ach.get("assessor"), "triage": c.triage})


@mcp.tool()
def get_risk_and_baselines(case_id: str) -> str:
    """Return each observation's baseline comparison, the deterministic risk index and the triage estimate.
    The triage probability is an uncalibrated internal estimate, never evidence."""
    c = _case(case_id)
    return _json({"risk_index": c.risk, "triage": c.triage,
                  "checks": [{"observation_id": o.observation_id, "type": o.type, **o.baseline} for o in c.observations]})


@mcp.tool()
def get_ach_matrix(case_id: str) -> str:
    """Return the ACH matrix (rows = independence groups), rankings and contradictions."""
    c = _case(case_id)
    return _json({"ach": {k: v for k, v in c.ach.items() if k not in ("proposals", "edits")},
                  "contradictions": c.contradictions})


@mcp.tool()
def get_legal_mapping(case_id: str) -> str:
    """Return case facts, proposed/confirmed circumstances and rules-engine output (decision support only)."""
    return _json(_case(case_id).legal)


@mcp.tool()
def verify_text(case_id: str, text: str) -> str:
    """Run the deterministic Verifier on draft text: citations, confirmed observations, forbidden phrasing."""
    return _json(ENGINE.verify_text(case_id, text))


@mcp.tool()
def review_observation(
    case_id: str,
    observation_id: str,
    status: str,
    reviewer: str = "investigator",
    reason: str = "",
) -> str:
    """
    Record human review of an observation.
    status must be accepted, rejected, or unreviewed.
    """
    if status not in {"accepted", "rejected", "unreviewed"}:
        raise ValueError("status must be accepted, rejected, or unreviewed")
    ENGINE.review(case_id, observation_id, status, reviewer, reason)
    return _json({"case_id": case_id, "observation_id": observation_id, "review_status": status,
                  "reviewer": reviewer, "reason": reason})


@mcp.tool()
def generate_report(case_id: str) -> str:
    """Generate the draft package: verified brief, evidence matrix, BSA 63(4) certificate draft,
    victim guides, technical report and manifest."""
    updated = ENGINE.generate_report(case_id)
    return _json({"status": updated.status, "reports": updated.reports,
                  "unsupported_sentences": updated.brief.get("unsupported_sentences"),
                  "ledger": STORE.ledger(case_id).verify()})


@mcp.tool()
def get_visual_analysis(case_id: str) -> str:
    """
    Return a focused visual-forensics summary for a case.
    Includes agent status, frames examined, faces detected,
    visual observations, artifact list, model availability,
    tool availability, warnings, and limitations.
    """
    c = _case(case_id)
    ar = c.agent_runs.get("visual-forensics")
    visual_obs = [o.model_dump() for o in c.observations
                  if o.agent_id in {"visual-forensics"}]

    # Extract frame / face counts from observations
    frames_examined = None
    faces_detected  = None
    for o in c.observations:
        if o.type == "visual.face_detection":
            frames_examined = o.measurement.get("frames_examined")
            faces_detected  = o.measurement.get("faces_detected")
            break

    from app.forensics.tooling import resolve_executable
    tools = {
        t: resolve_executable(t)
        for t in ("ffmpeg", "ffprobe", "exiftool", "c2patool")
    }
    # Strip full path to avoid leaking install layout in responses
    tool_summary = {
        name: {"available": info["available"], "version": info["version"]}
        for name, info in tools.items()
    }

    return _json({
        "case_id":         case_id,
        "agent_status":    ar.status if ar else "not_registered",
        "agent_version":   ar.version if ar else None,
        "duration_ms":     ar.duration_ms if ar else None,
        "frames_examined": frames_examined,
        "faces_detected":  faces_detected,
        "observation_count": len(visual_obs),
        "observations":    visual_obs,
        "artifact_ids":    ar.artifact_ids if ar else [],
        "warnings":        ar.warnings if ar else [],
        "error":           ar.error if ar else None,
        "tool_availability": tool_summary,
        "ml_model": {
            "status": "unavailable",
            "note":   "No optional ONNX deepfake model is currently installed.",
        },
        "limitations": [
            "Automated visual screening is not a binary truth detector.",
            "Model scores are not probabilities without a validated operating point.",
            "Face detection absence does not indicate absence of a person.",
        ],
    })


@mcp.tool()
def sign_off_case(case_id: str, reviewer: str, statement: str, role: str = "officer") -> str:
    """
    Record a human sign-off (role officer or supervisor). Two different people must sign;
    the second sign-off writes the final package and seals the ledger.
    Sign-off is a human review action; it is not an AI finding.
    """
    if role not in {"officer", "supervisor"}:
        raise ValueError("role must be officer or supervisor")
    updated = ENGINE.signoff(case_id, reviewer, role, statement)
    return _json({"status": updated.status, "signoffs": updated.signoffs, "sealed": updated.sealed,
                  "reports": updated.reports, "ledger": STORE.ledger(case_id).verify()})


if __name__ == "__main__":
    # STDIO is the intended local Bob transport.
    # IBM Bob launches this process and communicates over stdin/stdout.
    mcp.run()
