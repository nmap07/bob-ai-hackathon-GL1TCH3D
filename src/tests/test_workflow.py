"""End-to-end workflow, baselines, verifier, legal engine and API security."""
import asyncio, io, json, threading
from pathlib import Path

import pytest
from PIL import Image

from app import baselines
from app.engine import CaseError, InvestigationEngine
from app.store import CaseStore, HashChain, LedgerSealedError


def _jpeg(tmp_path, name="e.jpg"):
    p = tmp_path / name
    buf = io.BytesIO(); Image.new("RGB", (96, 96), (120, 80, 60)).save(buf, format="JPEG"); p.write_bytes(buf.getvalue())
    return p


@pytest.fixture
def case(tmp_path):
    store = CaseStore(tmp_path / "cases"); eng = InvestigationEngine(store)
    c = asyncio.run(eng.create_case(_jpeg(tmp_path), "t", intake_details={"officer_name": "SI A"}))
    return eng, store, c


# ---------------------------------------------------------------- baselines
def test_every_observation_has_a_baseline(case):
    _, _, c = case
    assert c.observations
    for o in c.observations:
        assert o.baseline["profile"] == baselines.PROFILE_ID
        assert o.baseline["level"] in {"within", "elevated", "high", "not_scored", "insufficient_data"}
        assert o.baseline["calibrated"] is False
        assert o.independence_group


def test_baseline_levels_and_categories():
    a = baselines.assess("av_sync.stream_start_offset", {"offset_ms": 200}, "video", "av_sync")
    assert a["level"] == "high" and a["supports"]
    assert baselines.assess("av_sync.stream_start_offset", {"offset_ms": 10}, "video", "av_sync")["level"] == "within"
    g = baselines.assess("metadata.software_tag", {"values": ["Stable Diffusion XL"]}, "image", "metadata_software")
    assert g["level"] == "high" and "H3" in g["supports"]
    # Absence of provenance is never scored.
    assert baselines.assess("provenance.c2pa", {"manifest_present": False}, "image", "provenance")["points"] == 0


def test_risk_counts_correlated_detectors_once():
    b = baselines.assess("visual.face_boundary_variation", {"coefficient_of_variation": 0.9}, "video", "face_boundary")
    one = [{"observation_id": "OBS-a", "independence_group": "X:face_boundary", "review_status": "unreviewed", "baseline": b}]
    five = [dict(one[0], observation_id=f"OBS-{i}") for i in range(5)]
    assert baselines.compute_risk(one)["risk_score"] == baselines.compute_risk(five)["risk_score"] > 0
    assert baselines.compute_risk([dict(one[0], review_status="rejected")])["risk_score"] == 0


def test_triage_probability_is_labelled_and_bounded(case):
    _, _, c = case
    t = c.triage
    assert 0 <= t["probability_manipulated"] <= 1
    assert t["probability_label"] in {"llm_estimate_uncalibrated", "heuristic_from_risk_index"}
    assert "Excluded from the investigation brief" in t["policy"]


# ---------------------------------------------------------------- verifier
def test_verifier_rejects_uncited_and_overclaiming(case):
    eng, _, c = case
    oid = c.observations[0].observation_id
    eng.review(c.case_id, oid, "accepted", "analyst")
    r = eng.verify_text(c.case_id, f"The boundary artifact proves the video is fake [{oid}]. "
                                   f"Compression anomalies were detected across the face region without any citation.")
    assert r["failed"] == 2
    ok = eng.verify_text(c.case_id, f"The measurement is an uncalibrated indicator consistent with recompression [{oid}].")
    assert ok["failed"] == 0
    unconfirmed = next(o.observation_id for o in c.observations if o.observation_id != oid)
    bad = eng.verify_text(c.case_id, f"The observation is consistent with benign processing [{unconfirmed}].")
    assert "not been confirmed" in json.dumps(bad)


# ---------------------------------------------------------------- legal
def test_legal_excludes_female_worded_sections_for_male_victim(case):
    eng, _, c = case
    facts = {"victim_gender": "male", "intimate_content": True, "demand_made": True, "possible_minor": False}
    s = eng.set_legal(c.case_id, "SI A", facts)
    assert "extortion" in {p["circumstance_key"] for p in s.legal["proposals"]}
    s = eng.set_legal(c.case_id, "SI A", facts, ["non_consensual_intimate", "extortion"])
    sec = {x["section"]: x for r in s.legal["results"] for x in r["sections"]}
    assert sec["77"]["excluded"] is True
    assert sec["308"]["excluded"] is False
    with pytest.raises(CaseError):
        eng.set_legal(c.case_id, "SI A", {"victim_gender": "robot"})


# ---------------------------------------------------------------- full workflow
def test_full_workflow_to_sealed_package(case):
    eng, store, c = case
    ids = [o.observation_id for o in c.observations]
    with pytest.raises(CaseError):                      # S5 gate
        eng.accept_ach(c.case_id, "analyst")
    eng.bulk_review(c.case_id, ids, "accepted", "Analyst B")
    eng.accept_ach(c.case_id, "Analyst B")
    eng.set_legal(c.case_id, "SI A", {"victim_gender": "female", "demand_made": True})
    eng.set_legal(c.case_id, "SI A", {"victim_gender": "female", "demand_made": True}, ["extortion", "electronic_evidence"])
    s = eng.generate_report(c.case_id)
    assert s.brief["unsupported_sentences"] == 0
    brief = Path(s.reports["brief"]).read_text(encoding="utf-8")
    assert "[RULE-extortion]" in brief and "%" not in brief
    assert str(s.triage["probability_manipulated"]) not in brief.split("## 9.")[0]
    cert = Path(s.reports["certificate"]).read_text(encoding="utf-8")
    assert c.original.sha256 in cert and "Signature: ______" in cert
    assert Path(s.reports["victim_guide_hi"]).exists()
    eng.signoff(c.case_id, "SI A", "officer", "reviewed")
    with pytest.raises(CaseError):                      # same person cannot sign twice
        eng.signoff(c.case_id, "SI A", "supervisor", "reviewed")
    s = eng.signoff(c.case_id, "Insp C", "supervisor", "approved")
    assert s.sealed and s.status == "complete"
    v = store.ledger(c.case_id).verify()
    assert v["valid"] and v["head"] == s.ledger["final_head"]
    with pytest.raises(CaseError):                      # sealed cases are immutable
        eng.review(c.case_id, ids[0], "rejected", "x")
    manifest = json.loads(Path(s.reports["manifest"]).read_text())
    assert manifest["report_hash"] == s.ledger["report_hash"]


def test_change_after_signoff_voids_it(case):
    eng, _, c = case
    ids = [o.observation_id for o in c.observations]
    eng.bulk_review(c.case_id, ids, "accepted", "B"); eng.accept_ach(c.case_id, "B")
    eng.set_legal(c.case_id, "A", {"demand_made": True}, ["extortion"])
    eng.generate_report(c.case_id); eng.signoff(c.case_id, "A", "officer", "ok")
    s = eng.review(c.case_id, ids[0], "rejected", "B", "re-check")
    assert s.signoffs == []
    with pytest.raises(CaseError):                      # stale draft
        eng.signoff(c.case_id, "A", "officer", "ok")


def test_original_is_read_only_and_envelopes_written(case):
    _, store, c = case
    import os
    assert not os.access(c.original.path, os.W_OK)
    for ar in c.agent_runs.values():
        if ar.status != "not_applicable":
            env = json.loads(Path(ar.envelope_path).read_text())
            assert env["schema_version"] == "EMAFIG-FR-1.0"
            assert env["inputs"]["artifacts"][0]["source_hash_verified"] is True


# ---------------------------------------------------------------- ledger
def test_ledger_concurrent_appends_stay_chained(tmp_path):
    led = HashChain(tmp_path / "l.jsonl")
    ts = [threading.Thread(target=lambda i=i: [led.append("E", "C", {"i": i, "j": j}) for j in range(10)]) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    v = led.verify()
    assert v["valid"] and v["entries"] == 60
    led.append("LEDGER_SEALED", "C", {})
    with pytest.raises(LedgerSealedError):
        led.append("E", "C", {})


# ---------------------------------------------------------------- API security
def test_api_requires_token_and_host(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAFIG_CASES_DIR", str(tmp_path / "cases"))
    import importlib, app.main as m
    m = importlib.reload(m)
    from fastapi.testclient import TestClient
    cl = TestClient(m.app)
    assert cl.get("/api/health").status_code == 200
    assert m.API_TOKEN in cl.get("/").text
    assert cl.post("/api/cases/X/report").status_code == 403
    assert cl.post("/api/cases/X/report", headers={"X-EMAFIG-Token": m.API_TOKEN}).status_code == 404
    assert cl.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    buf = io.BytesIO(); Image.new("RGB", (64, 64)).save(buf, format="PNG")
    r = cl.post("/api/cases", files={"file": ("x.png", buf.getvalue(), "image/png")},
                data={"officer_name": "SI A"}, headers={"X-EMAFIG-Token": m.API_TOKEN})
    assert r.status_code == 200
    got = cl.get(f"/api/cases/{r.json()['case_id']}").json()
    assert got["status"] == "awaiting_review" and got["risk"]["risk_score"] is not None
