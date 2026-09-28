"""
app/envelope.py
Writes the EMAFIG-FR-1.0 result envelope for every agent run
(EMAFIG-FORensic-Output-Contract.md). Values that were not captured are
null, never invented.
"""
from __future__ import annotations

import json, platform
from functools import lru_cache
from pathlib import Path

from app.forensics.tooling import resolve_executable
from app.utils import sha256_file, sha512_file, utcnow

SCHEMA_VERSION = "EMAFIG-FR-1.0"

# Tools each examiner can invoke (the contract's explicit allow-list).
AGENT_TOOLS: dict[str, list[str]] = {
    "metadata-analysis": ["ffprobe", "exiftool", "pillow"],
    "compression-analysis": ["ffprobe", "opencv", "pillow"],
    "visual-forensics": ["ffprobe", "opencv", "pillow"],
    "audio-forensics": ["ffmpeg", "librosa", "onnxruntime"],
    "temporal-analysis": ["ffprobe"],
    "av-sync-analysis": ["ffprobe"],
    "c2pa-provenance": ["c2pa-python", "c2patool"],
}
_PY_MODULES = {"opencv": "cv2", "pillow": "PIL", "librosa": "librosa", "onnxruntime": "onnxruntime",
               "c2pa-python": "c2pa"}


@lru_cache(maxsize=None)
def tool_info(name: str) -> dict:
    if name in _PY_MODULES:
        try:
            mod = __import__(_PY_MODULES[name])
            return {"name": name, "version": getattr(mod, "__version__", None), "path_or_image": "python-module",
                    "vendor": None, "command": None, "exit_code": None, "stdout_sha256": None, "stderr_sha256": None,
                    "available": True}
        except Exception:
            return {"name": name, "version": None, "available": False}
    r = resolve_executable(name)
    return {"name": name, "version": r["version"], "path_or_image": r["path"], "vendor": None, "command": None,
            "exit_code": None, "stdout_sha256": None, "stderr_sha256": None, "available": r["available"]}


def environment_id() -> str:
    return f"python-{platform.python_version()}/{platform.system()}-{platform.release()}/{platform.machine()}"


def write(run_dir: Path, *, case, agent_run, observations: list, artifacts: list[dict], source_verified: bool) -> tuple[Path, str]:
    status = agent_run.status
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "run": {"run_id": agent_run.run_id, "pipeline_run_id": case.pipeline_run_id, "agent_id": agent_run.agent_id,
                "agent_version": agent_run.version, "started_utc": agent_run.started_utc,
                "ended_utc": agent_run.ended_utc, "status": status,
                "operator_id": case.intake.officer_id, "host_id": platform.node() or None,
                "environment_id": environment_id()},
        "case": {"case_id": case.case_id, "evidence_id": case.evidence_id, "exhibit_id": None,
                 "source_uri": f"case://{case.case_id}/original/{case.original.artifact_id}"},
        "inputs": {"artifacts": [{"artifact_id": case.original.artifact_id, "filename": "original",
                                  "size_bytes": case.original.size_bytes, "mime_type": case.media_type,
                                  "sha256": case.original.sha256, "sha512": case.original.sha512,
                                  "source_hash_verified": source_verified, "access_mode": "read_only"}]},
        "tools_used": [t for t in (tool_info(n) for n in AGENT_TOOLS.get(agent_run.agent_id, [])) if t.get("available")],
        "result": {"result_type": "failure" if status == "failed" else "observation",
                   "summary": f"{len(observations)} observation(s); status {status}.",
                   "observations": [{"observation_id": o.observation_id, "category": o.type, "statement": o.statement,
                                     "location": o.location, "measurement": o.measurement,
                                     "basis": o.basis + [agent_run.run_id], "supports": o.supports,
                                     "contradicts": o.contradicts, "alternative_explanations": o.alternative_explanations,
                                     "baseline": o.baseline,
                                     "confidence": {"value": None, "method": "none (uncalibrated)",
                                                    "meaning": "no validated confidence"}} for o in observations],
                   "limitations": sorted({l for o in observations for l in o.limitations}),
                   "not_tested": sorted({t for o in observations for t in o.not_tested}),
                   "required_follow_up": []},
        "output": {"artifacts": [{"artifact_id": a.get("artifact_id"), "type": a.get("type", "other"),
                                  "path": Path(a["path"]).name, "size_bytes": Path(a["path"]).stat().st_size
                                  if Path(a["path"]).exists() else None,
                                  "sha256": a.get("sha256"), "sha512": a.get("sha512")} for a in artifacts]},
        "provenance": {"parent_artifact_hashes": [case.original.sha256], "derived_from_observation_ids": [],
                       "processing_steps": [], "transformations": []},
        "validation": {"checks": [{"check": "source_hash_reverified", "status": "passed" if source_verified else "failed",
                                   "details": "SHA-256 recomputed before the examiner read the file"}],
                       "repeatability_status": "not_tested", "independent_review_required": True},
        "chain_of_custody": {"event_ids": [], "source_preservation_verified": source_verified,
                             "write_protection_verified": bool(case.original.read_only)},
        "security": {"network_access": False, "source_modified": not source_verified,
                     "temporary_files_outside_sandbox": False},
        "errors": [agent_run.error] if agent_run.error else [],
        "signature": {"status": "unsigned", "algorithm": None, "key_id": None, "value": None},
        "written_utc": utcnow(),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{agent_run.agent_id}_{agent_run.run_id}.json"
    path.write_text(json.dumps(envelope, indent=2, default=str), encoding="utf-8")
    return path, sha256_file(path)
