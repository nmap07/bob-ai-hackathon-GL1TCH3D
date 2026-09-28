"""
tests/test_visual_failure_modes.py
Visual pipeline failure mode tests — missing tools, missing models,
unsupported files, corrupted inputs, etc.
"""
import asyncio
import io
from pathlib import Path

import pytest

from app.agents import visual
from app.store import CaseStore
from app.engine import InvestigationEngine


def _minimal_jpeg(w=64, h=64) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(60, 120, 180)).save(buf, format="JPEG")
    return buf.getvalue()


def _minimal_png(w=32, h=32) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Missing tools — visual agent must NEVER fail just because a tool is absent
# ---------------------------------------------------------------------------

def test_missing_exiftool_does_not_fail_image(tmp_path, monkeypatch):
    """Missing ExifTool must only add a warning, not fail metadata or visual agent."""
    import app.forensics.tooling as tooling
    original = tooling.resolve_executable
    def mock(name):
        if name == "exiftool":
            return {"available": False, "path": None, "version": None,
                    "error": "mocked absent"}
        return original(name)
    monkeypatch.setattr(tooling, "resolve_executable", mock)

    src = tmp_path / "img.jpg"
    src.write_bytes(_minimal_jpeg())
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "no exiftool"))

    ar_meta = c.agent_runs["metadata-analysis"]
    assert ar_meta.status in {"completed", "completed_with_warnings"}

    ar_vis  = c.agent_runs["visual-forensics"]
    assert ar_vis.status in {"completed", "completed_with_warnings"}


def test_missing_ffprobe_does_not_fail_image_visual(tmp_path, monkeypatch):
    """Missing ffprobe must not affect image visual forensics."""
    import app.forensics.tooling as tooling
    original = tooling.resolve_executable
    def mock(name):
        if name == "ffprobe":
            return {"available": False, "path": None, "version": None,
                    "error": "mocked absent"}
        return original(name)
    monkeypatch.setattr(tooling, "resolve_executable", mock)

    src = tmp_path / "img.png"
    src.write_bytes(_minimal_png())
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "no ffprobe image"))

    ar_vis = c.agent_runs["visual-forensics"]
    assert ar_vis.status in {"completed", "completed_with_warnings"}, (
        f"Image visual pipeline must not fail without ffprobe. Got: {ar_vis.status}, "
        f"error: {ar_vis.error}"
    )


def test_missing_onnx_model_does_not_fail_visual(tmp_path):
    """Absent ONNX deepfake model must produce 'unavailable', not fail the agent."""
    from app.forensics.deepfake_model import analyze_image
    result = analyze_image(
        image_path=tmp_path / "img.jpg",
        model_path=tmp_path / "nonexistent.onnx",
        model_name="test-model",
    )
    assert result.status == "unavailable"
    assert result.raw_score is None


def test_haar_cascade_missing_does_not_fail_agent(tmp_path, monkeypatch):
    """Missing Haar cascade must add a warning and produce face_detection observation,
    but must NOT raise or fail the entire visual agent."""
    import app.agents.visual as vis_mod
    # Monkeypatch _load_face_cascade to return None
    monkeypatch.setattr(vis_mod, "_load_face_cascade", lambda: None)

    src = tmp_path / "img.jpg"
    src.write_bytes(_minimal_jpeg())
    out = tmp_path / "artifacts"
    out.mkdir()
    obs, arts, warnings = vis_mod.run(src, out, "EVD-test", "image")

    types = {o.type for o in obs}
    assert "visual.face_detection" in types
    fobs = next(o for o in obs if o.type == "visual.face_detection")
    assert fobs.measurement["cascade_available"] is False
    # Must warn, not raise
    assert any("cascade" in w.lower() or "haar" in w.lower() for w in warnings)


def test_corrupted_image_agent_status(tmp_path):
    """Corrupted image file: visual agent FAILED is correct, engine must not crash."""
    src = tmp_path / "corrupt.jpg"
    src.write_bytes(b"GARBAGE DATA\xff\xfe\x00NOT AN IMAGE")
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "corrupt"))
    # Engine saved the case — pipeline continued despite agent failure
    assert c.case_id
    assert store.load(c.case_id) is not None


def test_unsupported_media_type(tmp_path):
    """Unsupported extension ('.xyz'): engine must save case, agent fails gracefully."""
    src = tmp_path / "evidence.xyz"
    src.write_bytes(_minimal_jpeg())  # valid JPEG bytes in an unsupported-named file
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "unsupported"))
    assert c.case_id
    # Case must be persisted
    assert store.load(c.case_id) is not None


def test_no_silent_failures(tmp_path):
    """Any agent failure must record the error in agent_runs.error, not hide it."""
    src = tmp_path / "corrupt.bin"
    src.write_bytes(b"\x00" * 100)
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "silent fail check"))

    for aid, ar in c.agent_runs.items():
        if ar.status == "failed":
            assert ar.error is not None, (
                f"Agent {aid} has status=failed but error is None (silent failure)"
            )


def test_all_observations_have_required_fields(tmp_path):
    """All observations across the pipeline must have required schema fields."""
    src = tmp_path / "schema.png"
    src.write_bytes(_minimal_png())
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "schema test"))

    for obs in c.observations:
        assert obs.observation_id, "observation_id must not be empty"
        assert obs.agent_id, "agent_id must not be empty"
        assert obs.agent_version, "agent_version must not be empty"
        assert obs.type, "type must not be empty"
        assert obs.statement, "statement must not be empty"
        assert isinstance(obs.basis, list), "basis must be a list"
        assert len(obs.basis) >= 1, "basis must have at least one entry"
        assert isinstance(obs.alternative_explanations, list)
        assert isinstance(obs.limitations, list)
        assert isinstance(obs.calibrated, bool)
        assert obs.review_status in {"unreviewed", "accepted", "rejected"}


def test_ledger_integrity_after_agent_failure(tmp_path):
    """Audit ledger must remain valid even when an agent fails."""
    src = tmp_path / "ledger_test.jpg"
    src.write_bytes(_minimal_jpeg())
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "ledger test"))
    result = store.ledger(c.case_id).verify()
    assert result["valid"] is True, f"Ledger invalid: {result.get('error')}"
