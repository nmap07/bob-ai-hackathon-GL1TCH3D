"""
app/engine.py
Orchestrator: drives the case lifecycle of plan §5, enforces the gates,
records every step in the hash-chained ledger, and keeps Plane B (Bob) behind
schema-validated contracts.

S0 intake -> S2 examiners (parallel) -> baseline + independence + risk ->
ACH proposal (Bob/fallback) -> skeptic -> triage estimate -> S5 officer review
-> S7 ACH acceptance -> S8 gaps -> S9 legal facts + confirmation ->
S10 draft + Verifier -> S11 two sign-offs, final package, ledger seal.
"""
from __future__ import annotations

import asyncio, json, os, re
from pathlib import Path
from typing import Any

from app import baselines, envelope, reasoning, reporting
from app.agents import intake, metadata, visual, temporal, compression, audio, av_sync, provenance
from app.bob import BobClient
from app.schemas import (AgentRun, CaseState, Hypothesis, IntakeDetails, Observation)
from app.store import CaseStore, LedgerSealedError
from app.utils import utcnow, new_id, environment_identity, sha256_file, canonical, sha256_bytes
from core.plane_c.ach import MISSING_EVIDENCE_CHECKLIST
from core.plane_c.custody import CustodyLog
from core.plane_c.legal_engine import LegalRulesEngine, RULES_TABLE_VERSION

CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")

# agent id, version, media types it applies to
AGENTS = [
    ("metadata-analysis", metadata.VERSION, {"image", "video", "audio"}),
    ("compression-analysis", compression.VERSION, {"image", "video"}),
    ("visual-forensics", visual.VERSION, {"image", "video"}),
    ("audio-forensics", audio.VERSION, {"video", "audio"}),
    ("temporal-analysis", temporal.VERSION, {"video"}),
    ("av-sync-analysis", av_sync.VERSION, {"video"}),
    ("c2pa-provenance", provenance.VERSION, {"image", "video", "audio", "other"}),
]

LEGAL_FACTS: dict[str, Any] = {
    "victim_gender": ("female", "male", "other", "unknown"),
    "possible_minor": bool, "demand_made": bool, "intimate_content": bool, "impersonation_detected": bool,
    "manipulation_detected": bool, "harassment_pattern": bool, "network_indicators": bool,
}
DERIVATIVE_TYPES = {"wav", "png"}


class CaseError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message); self.status = status


class InvestigationEngine:
    def __init__(self, store: CaseStore, bob: BobClient | None = None):
        self.store = store
        self.bob = bob or BobClient()
        self.rules = LegalRulesEngine()

    # ================================================================ helpers
    def _ledger(self, state, event, data):
        return self.store.ledger(state.case_id).append(event, state.case_id, data)

    def _custody(self, state) -> CustodyLog:
        return CustodyLog(self.store.case_dir(state.case_id) / "custody.jsonl")

    def _custody_event(self, state, kind: str, **kw):
        log = self._custody(state)
        ev = getattr(log, f"record_{kind}")(case_id=state.case_id, evidence_id=state.evidence_id, **kw)
        self._ledger(state, "CUSTODY", ev.to_dict())

    def _load(self, case_id) -> CaseState:
        s = self.store.load(case_id)
        if not s: raise CaseError(404, "case not found")
        return s

    def _mutable(self, case_id) -> CaseState:
        s = self._load(case_id)
        if s.sealed: raise CaseError(409, "case is sealed after final sign-off; start a new case to re-examine")
        if s.status in ("queued", "running"): raise CaseError(409, "analysis is still running")
        return s

    def _save(self, state):
        state.updated_utc = utcnow(); self.store.save(state)

    # ================================================================ intake
    def start_case(self, src: Path, description: str | None = None, case_id: str | None = None,
                   intake_details: IntakeDetails | dict | None = None) -> CaseState:
        case_id = case_id or f"CASE-{utcnow()[:19].replace('-', '').replace(':', '')}-{new_id('X').split('-')[-1]}"
        if not CASE_ID_RE.match(case_id):
            raise CaseError(422, "case_id may contain only letters, digits, '.', '_' and '-'")
        if self.store.exists(case_id):
            raise CaseError(409, f"case {case_id} already exists; every re-run needs a new case id")
        details = IntakeDetails.model_validate(intake_details or {})
        art = intake.ingest(Path(src), self.store.case_dir(case_id), case_id)
        mt = art["type"] if art["type"] in ("image", "video", "audio") else "other"
        now = utcnow()
        state = CaseState(case_id=case_id, evidence_id=new_id("EVD"), filename=Path(src).name, media_type=mt,
                          status="queued", stage="intake", created_utc=now, updated_utc=now,
                          source_description=description, pipeline_run_id=new_id("RUN"), original=art,
                          intake=details, baseline_profile=baselines.PROFILE_ID)
        state.artifacts.append({"artifact_id": art["artifact_id"], "file_name": state.filename, "sha256": art["sha256"],
                                "producer": intake.AGENT_ID, "type": "original", "derivative": False})
        for aid, ver, applies in AGENTS:
            ar = AgentRun(agent_id=aid, version=ver, run_id=new_id("AR"))
            if mt not in applies:
                ar.status = "not_applicable"; ar.started_utc = ar.ended_utc = now
            state.agent_runs[aid] = ar
        self.store.save(state)
        self._ledger(state, "CASE_CREATED", {"original": art, "environment": environment_identity(),
                                             "pipeline_run_id": state.pipeline_run_id,
                                             "intake": details.model_dump(exclude_none=True),
                                             "baseline_profile": baselines.PROFILE_ID,
                                             "baseline_version": baselines.PROFILE_VERSION})
        self._custody_event(state, "received", actor_id=details.officer_id or "unrecorded",
                            actor_name=details.officer_name or "unrecorded officer",
                            from_actor=details.how_received or "submitter", actor_role="first_responder",
                            seizure_memo_ref=details.seizure_memo_ref, notes=description)
        for aid, ar in state.agent_runs.items():
            if ar.status == "not_applicable":
                self._ledger(state, "AGENT_NOT_APPLICABLE", {"agent": aid, "media_type": mt})
        return state

    async def create_case(self, src: Path, description: str | None = None, case_id: str | None = None,
                          intake_details: IntakeDetails | dict | None = None) -> CaseState:
        """Intake + full analysis (CLI, tests, MCP)."""
        state = self.start_case(src, description, case_id, intake_details)
        await self.run_analysis(state.case_id)
        return self._load(state.case_id)

    # ================================================================ examiners
    async def run_analysis(self, case_id: str):
        state = self._load(case_id)
        state.status = "running"; state.stage = "examiners"; self._save(state)
        try:
            ok = await asyncio.to_thread(intake.verify, Path(state.original.path), state.original.sha256)
            state.ledger["source_reverified"] = ok
            self._ledger(state, "SOURCE_REVERIFIED", {"sha256": state.original.sha256, "match": ok})
            if not ok:
                for ar in state.agent_runs.values():
                    if ar.status == "queued":
                        ar.status = "failed"; ar.error = "source hash mismatch before read; escalate to operator"
                state.status = "failed"; state.errors.append("Original evidence hash mismatch; analysis refused.")
                self._save(state); return
            self._custody_event(state, "access", actor_id="system", actor_name="EMAFIG orchestrator",
                                actor_role="system", reason="automated examination of the preserved original")
            out = self.store.case_dir(case_id) / "artifacts"
            media, mt, ev = Path(state.original.path), state.media_type, state.evidence_id
            model = Path(os.getenv("AASIST_MODEL", "models/audio/aasist.onnx"))
            fns = {
                "metadata-analysis": lambda: metadata.run(media, out, ev, mt),
                "compression-analysis": lambda: compression.run(media, out, ev, mt),
                "visual-forensics": lambda: visual.run(media, out, ev, mt),
                "audio-forensics": lambda: audio.run(media, out, ev, model),
                "temporal-analysis": lambda: temporal.run(media, out, ev),
                "av-sync-analysis": lambda: av_sync.run(media, out, ev, mt),
                "c2pa-provenance": lambda: provenance.run(media, out, ev),
            }
            await asyncio.gather(*[self._one(state, aid, fns[aid]) for aid, ar in state.agent_runs.items()
                                   if ar.status == "queued"])
            state.stage = "reasoning"; self._save(state)
            await self._reason(state)
            state.stage = "review"; state.status = "awaiting_review"
            self._ledger(state, "REASONING_COMPLETED", {"risk_score": state.risk.get("risk_score"),
                                                        "ach_ranking": (state.ach.get("ranking_provisional") or {}).get("ranking"),
                                                        "bob": {k: v.get("provider") for k, v in state.bob.items()}})
        except Exception as e:
            state.status = "failed"; state.errors.append(f"orchestrator: {e!r}")
            self._ledger(state, "PIPELINE_FAILED", {"error": repr(e)})
        self._save(state)

    async def _one(self, state, aid, fn):
        ar = state.agent_runs[aid]; ar.status = "running"; ar.started_utc = utcnow()
        loop = asyncio.get_running_loop(); start = loop.time()
        self._save(state)
        obs, arts = [], []
        try:
            obs, arts, warns = await asyncio.to_thread(fn)
            ar.status = "completed_with_warnings" if warns else "completed"
            ar.warnings.extend(warns)
            for a in arts:
                a.setdefault("artifact_id", new_id("ART"))
                state.artifacts.append({"artifact_id": a["artifact_id"], "file_name": Path(a["path"]).name,
                                        "sha256": a.get("sha256"), "producer": aid, "type": a.get("type"),
                                        "derivative": a.get("type") in DERIVATIVE_TYPES,
                                        "derivative_id": a.get("derivative_id")})
                ar.artifact_ids.append(a["artifact_id"])
            for o in obs:
                state.observations.append(o); ar.observation_ids.append(o.observation_id)
        except Exception as e:
            ar.status = "failed"; ar.error = repr(e); state.errors.append(f"{aid}: {e}")
        ar.ended_utc = utcnow(); ar.duration_ms = int((loop.time() - start) * 1000)
        try:
            path, sha = envelope.write(self.store.case_dir(state.case_id) / "runs", case=state, agent_run=ar,
                                       observations=obs, artifacts=arts,
                                       source_verified=bool(state.ledger.get("source_reverified")))
            ar.envelope_path, ar.envelope_sha256 = str(path), sha
        except Exception as e:
            ar.warnings.append(f"envelope not written: {e!r}")
        self._ledger(state, "AGENT_FAILED" if ar.status == "failed" else "AGENT_COMPLETED",
                     {"agent": aid, "run_id": ar.run_id, "status": ar.status, "observations": len(obs),
                      "artifacts": [{"id": a.get("artifact_id"), "sha256": a.get("sha256")} for a in arts],
                      "warnings": ar.warnings, "error": ar.error, "envelope_sha256": ar.envelope_sha256})
        self._save(state)

    # ================================================================ reasoning
    def _annotate(self, state):
        for o in state.observations:
            fam = reasoning.family_of(o.type)
            o.independence_group = f"{o.derivative_id or state.original.artifact_id}:{fam}"
            o.baseline = baselines.assess(o.type, o.measurement, state.media_type, fam)
            if o.source == "tool":
                o.supports = list(o.baseline.get("supports") or [])

    def _obs_dicts(self, state):
        return [o.model_dump() for o in state.observations]

    def _recompute(self, state):
        """Deterministic stages: baselines, independence, risk index, ACH matrix, contradictions, gaps."""
        self._annotate(state)
        od = self._obs_dicts(state)
        state.risk = baselines.compute_risk(od)
        groups = reasoning.groups_of(od)
        ach = state.ach or {}
        proposals = dict(ach.get("proposals") or {})
        missing = {g: m for g, m in groups.items() if g not in proposals}
        if missing:
            for c in reasoning.fallback_ach(missing)["cells"]:
                proposals.setdefault(c["group_id"], {})[c["hypothesis_id"]] = {
                    "value": c["value"], "reason": c["reason"], "proposed_by": "rule-fallback"}
        edits = ach.get("edits") or {}
        view = reasoning.build_ach(groups, proposals, edits)
        view.update(proposals=proposals, edits=edits, accepted_by=ach.get("accepted_by"),
                    accepted_utc=ach.get("accepted_utc"), assessor=ach.get("assessor", "rule-fallback"))
        state.ach = view
        state.contradictions = reasoning.contradictions_from_ach(view)
        rows = {r["group_id"]: r for r in view["rows"]}
        state.hypotheses = []
        for h in view["hypotheses"]:
            sup = [i for r in rows.values() if r["diagnostic"] and r["points"] > 0 and r["cells"][h["id"]]["value"] == "C"
                   for i in r["observation_ids"]]
            con = [i for r in rows.values() if r["diagnostic"] and r["cells"][h["id"]]["value"] == "I"
                   for i in r["observation_ids"]]
            used = set(sup + con)
            state.hypotheses.append(Hypothesis(id=h["id"], label=h["label"], description=h["description"],
                                               support_observation_ids=sup, contradiction_observation_ids=con,
                                               uninformative_observation_ids=[o["observation_id"] for o in od
                                                                              if o["observation_id"] not in used]))
        self._missing(state)
        state.limitations = self._limitations(state)

    def _missing(self, state):
        gaps = []
        for aid, ar in state.agent_runs.items():
            if ar.status == "failed":
                gaps.append({"kind": "pipeline", "item": aid, "status": "failed", "impact": ar.error})
            elif ar.status == "completed_with_warnings":
                gaps.append({"kind": "pipeline", "item": aid, "status": "warnings", "impact": ar.warnings})
        collected = dict(state.collected_evidence)
        if state.intake.source_url: collected.setdefault("source_url", "collected")
        if any(o.type == "provenance.c2pa" and o.measurement.get("manifest_present") for o in state.observations):
            collected.setdefault("c2pa_manifest", "collected")
        for item in MISSING_EVIDENCE_CHECKLIST:
            g = {"kind": "checklist", **item, "status": collected.get(item["item"], "missing")}
            if item["item"] == "c2pa_manifest":
                g["note"] = "Absence of a C2PA credential is a gap, not evidence of fakery."
            gaps.append(g)
        state.missing_evidence = gaps

    def _limitations(self, state) -> list[str]:
        out = []
        for mode, rec in (state.bob or {}).items():
            if rec.get("status") != "ok":
                out.append(f"Bob mode '{mode}' not used ({rec.get('error')}); deterministic fallback applied.")
        if not state.original.read_only:
            out.append("The file system did not allow the stored original to be marked read-only.")
        return out

    def _bob(self, state, mode: str, payload: dict, fallback, extra=None) -> dict:
        rec = self.bob.ask(mode, payload, reasoning.SCHEMAS[mode], fallback, extra)
        arts = self.store.case_dir(state.case_id) / "artifacts"
        path = arts / f"bob_{mode}_{new_id('RAW')}.json"
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if rec["status"] == "awaiting_manual_reply":
            pdir = arts / "bob_prompts"; pdir.mkdir(exist_ok=True)
            (pdir / f"{mode}.txt").write_text(rec["prompt"], encoding="utf-8")
        sha = sha256_file(path)
        state.bob[mode] = {"provider": rec["provider"], "status": rec["status"], "error": rec.get("error"),
                           "artifact": path.name, "sha256": sha, "input_sha256": rec["input_sha256"],
                           "output_sha256": rec.get("output_sha256"), "at": utcnow(),
                           "attempts": len(rec["attempts"])}
        self._ledger(state, "AGENT_RUN", {"mode": mode, **{k: v for k, v in state.bob[mode].items() if k != "at"}})
        return rec

    async def _reason(self, state, call_bob: bool = True):
        self._recompute(state)
        if not call_bob:
            return
        od = self._obs_dicts(state)
        groups = reasoning.groups_of(od)
        payload = {"hypotheses": [{"id": h["id"], "label": h["label"], "description": h["description"]}
                                  for h in state.ach["hypotheses"]],
                   "groups": [{"group_id": g, "family": g.split(":", 1)[-1],
                               "observations": [reasoning.obs_for_bob(o) for o in m]} for g, m in groups.items()]}
        rec = await asyncio.to_thread(self._bob, state, "hypothesis-assessor", payload,
                                      lambda: reasoning.fallback_ach(groups), reasoning.ach_validator(set(groups)))
        label = "bob" if rec["status"] == "ok" else "rule-fallback"
        proposals: dict = {}
        for c in reasoning.fallback_ach(groups)["cells"]:   # fill any cell Bob left out
            proposals.setdefault(c["group_id"], {})[c["hypothesis_id"]] = {"value": c["value"], "reason": c["reason"],
                                                                          "proposed_by": "rule-fallback"}
        for c in rec["response"]["cells"]:
            proposals.setdefault(c["group_id"], {})[c["hypothesis_id"]] = {"value": c["value"], "reason": c["reason"],
                                                                          "proposed_by": label}
        state.ach = {**state.ach, "proposals": proposals, "assessor": label}
        self._recompute(state)

        od = self._obs_dicts(state)
        ids = {o["observation_id"] for o in od}
        sk_obs = [reasoning.obs_for_bob(o) for o in reasoning.active(od)
                  if (o.get("baseline") or {}).get("points", 0) > 0 or o["review_status"] == "accepted"]
        rec = await asyncio.to_thread(self._bob, state, "skeptic", {"observations": sk_obs},
                                      lambda: reasoning.fallback_skeptic(od),
                                      reasoning.obs_validator(ids, "challenges"))
        state.challenges = [{**c, "provider": rec["provider"]} for c in rec["response"]["challenges"]]
        await asyncio.to_thread(self._triage, state)
        self._recompute(state)

    def _triage(self, state):
        od = self._obs_dicts(state)
        risk = state.risk
        payload = {"risk_index": {k: risk.get(k) for k in ("risk_score", "band", "method", "calibrated",
                                                           "interpretation", "contributions")},
                   "observations": [reasoning.obs_for_bob(o) for o in reasoning.active(od)],
                   "ach_ranking_provisional": (state.ach.get("ranking_provisional") or {}),
                   "media_type": state.media_type,
                   "instruction": "Weigh each baseline deviation against its alternatives. Give a likelihood band "
                                  "and a probability estimate labelled llm_estimate_uncalibrated."}
        rec = self._bob(state, "risk-assessor", payload, lambda: reasoning.fallback_risk(risk, od),
                        reasoning.risk_validator({o["observation_id"] for o in od}))
        state.triage = {**rec["response"], "provider": rec["provider"], "generated_utc": utcnow(),
                        "deterministic_risk_score": risk.get("risk_score"), "deterministic_band": risk.get("band"),
                        "policy": "Internal triage only. Excluded from the investigation brief and the BSA 63(4) "
                                  "certificate. Not calibrated; not a forensic probability."}

    # ================================================================ officer actions
    def _changed(self, state, why: str):
        """Any change after a draft makes the draft stale and voids existing sign-offs."""
        state.human_review["report_stale"] = bool(state.reports)
        if state.signoffs:
            self._ledger(state, "SIGNOFFS_INVALIDATED", {"reason": why, "signoffs": state.signoffs})
            state.signoffs = []
            if state.status == "awaiting_second_signoff": state.status = "awaiting_signoff"

    def _after_change(self, state, invalidate_ach: bool = True, why: str = "case changed"):
        self._changed(state, why)
        self._recompute(state)
        if invalidate_ach and state.ach.get("accepted_by"):
            self._ledger(state, "ACH_ACCEPTANCE_RESET", {"previous": state.ach["accepted_by"]})
            state.ach["accepted_by"] = state.ach["accepted_utc"] = None
        self._save(state)
        return state

    def review(self, case_id, observation_id, status, reviewer, reason=""):
        return self.bulk_review(case_id, [observation_id], status, reviewer, reason)

    def bulk_review(self, case_id, observation_ids, status, reviewer, reason=""):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            by_id = {o.observation_id: o for o in state.observations}
            unknown = [i for i in observation_ids if i not in by_id]
            if unknown: raise CaseError(404, f"unknown observation(s): {unknown[:5]}")
            for i in observation_ids:
                o = by_id[i]
                o.review_status, o.reviewed_by, o.reviewed_utc, o.review_reason = status, reviewer, utcnow(), reason
                self._ledger(state, "HUMAN_REVIEW", {"observation_id": i, "status": status, "reviewer": reviewer,
                                                     "reason": reason})
            return self._after_change(state)

    def add_officer_observation(self, case_id, reviewer, type_, statement, location=None, alternatives=None):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            slug = re.sub(r"[^a-z0-9_]+", "_", type_.lower()).strip("_") or "note"
            o = Observation(observation_id=new_id("OBS"), agent_id="officer", agent_version="n/a",
                            type=f"officer.{slug}", statement=statement, location=location or {},
                            basis=[state.evidence_id], source="officer",
                            alternative_explanations=alternatives or [], review_status="accepted",
                            reviewed_by=reviewer, reviewed_utc=utcnow(),
                            limitations=["Human visual judgement; not a tool measurement."])
            state.observations.append(o)
            self._ledger(state, "HUMAN_OBSERVATION", o.model_dump())
            return self._after_change(state)

    def edit_ach(self, case_id, group_id, hypothesis_id, value, reason, editor):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            if group_id not in {r["group_id"] for r in state.ach.get("rows", [])}:
                raise CaseError(404, "unknown ACH row")
            if hypothesis_id not in reasoning.HYP_IDS: raise CaseError(404, "unknown hypothesis")
            state.ach.setdefault("edits", {}).setdefault(group_id, {})[hypothesis_id] = {
                "value": value, "reason": reason, "proposed_by": editor, "edited": True}
            self._ledger(state, "HUMAN_ACH_EDIT", {"group_id": group_id, "hypothesis_id": hypothesis_id,
                                                   "value": value, "reason": reason, "editor": editor})
            return self._after_change(state)

    def accept_ach(self, case_id, analyst):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            if not any(o.review_status == "accepted" for o in state.observations):
                raise CaseError(409, "gate S5: confirm at least one observation before accepting the ACH matrix")
            snap = sha256_bytes(canonical({k: state.ach[k] for k in ("rows", "ranking_confirmed")}).encode())
            state.ach["accepted_by"], state.ach["accepted_utc"], state.ach["accepted_sha256"] = analyst, utcnow(), snap
            self._ledger(state, "HUMAN_ACH_ACCEPTED", {"analyst": analyst, "matrix_sha256": snap})
            self._changed(state, "ACH accepted")
            self._save(state); return state

    def set_evidence_status(self, case_id, item, status, officer):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            if item not in {i["item"] for i in MISSING_EVIDENCE_CHECKLIST}: raise CaseError(404, "unknown checklist item")
            state.collected_evidence[item] = status
            self._ledger(state, "HUMAN_EVIDENCE_STATUS", {"item": item, "status": status, "officer": officer})
            return self._after_change(state, invalidate_ach=False)

    def _validate_facts(self, facts: dict) -> dict:
        clean = {}
        for k, v in facts.items():
            if k not in LEGAL_FACTS: raise CaseError(422, f"unknown case fact '{k}'")
            spec = LEGAL_FACTS[k]
            if spec is bool and not isinstance(v, bool): raise CaseError(422, f"'{k}' must be true/false")
            if isinstance(spec, tuple) and v not in spec: raise CaseError(422, f"'{k}' must be one of {spec}")
            clean[k] = v
        return clean

    def set_legal(self, case_id, officer, facts, confirmed=None):
        """Without `confirmed`: store facts and ask legal-proposer. With it: officer confirms (gate S9)."""
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            facts = self._validate_facts(facts or state.legal.get("facts") or {})
            keys = set(self.rules.get_all_keys())
            legal = dict(state.legal)
            legal.update(facts=facts, rules_version=RULES_TABLE_VERSION,
                         all_rules=[r.to_dict() for r in self.rules.evaluate_all(facts)])
            if confirmed is None:
                payload = {"case_facts": facts,
                           "circumstance_keys": [{"key": k, "label": self.rules.get_rule(k)["label"],
                                                  "preconditions": self.rules.get_rule(k).get("preconditions", {})}
                                                 for k in sorted(keys)],
                           "confirmed_observations": [{"observation_id": o.observation_id, "type": o.type,
                                                       "statement": o.statement[:300]}
                                                      for o in state.observations if o.review_status == "accepted"]}
                rec = self._bob(state, "legal-proposer", payload, lambda: reasoning.fallback_legal(facts, self.rules),
                                reasoning.legal_validator(keys))
                legal.update(proposals=rec["response"]["circumstances"], proposed_by=rec["provider"],
                             status="proposed", confirmed_by=None, confirmed_utc=None, confirmed_keys=[],
                             results=[r.to_dict() for r in self.rules.evaluate_multiple(
                                 [c["circumstance_key"] for c in rec["response"]["circumstances"]], facts)])
                self._ledger(state, "LEGAL_FACTS", {"officer": officer, "facts": facts,
                                                    "proposed": [c["circumstance_key"] for c in legal["proposals"]]})
            else:
                bad = [k for k in confirmed if k not in keys]
                if bad: raise CaseError(422, f"circumstances not in rules table: {bad}")
                results = [r.to_dict() for r in self.rules.evaluate_multiple(confirmed, facts)]
                legal.update(status="confirmed", confirmed_by=officer, confirmed_utc=utcnow(),
                             confirmed_keys=list(confirmed), results=results,
                             escalation=any(r["escalation_required"] and r["applicable"] for r in results))
                self._ledger(state, "HUMAN_LEGAL_CONFIRMED", {"officer": officer, "facts": facts,
                                                              "circumstances": list(confirmed),
                                                              "escalation": legal["escalation"]})
            state.legal = legal
            self._changed(state, "legal mapping changed")
            self._save(state); return state

    def verify_text(self, case_id, text):
        return reporting.verify_text(self._load(case_id), text)

    def set_analyst_assessment(self, case_id, analyst, text):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            rep = reporting.verify_text(state, text)
            state.analyst_assessment = {"analyst": analyst, "text": text, "at": utcnow(), "verification": rep}
            self._ledger(state, "HUMAN_ASSESSMENT", {"analyst": analyst, "text_sha256": sha256_bytes(text.encode()),
                                                     "failed_sentences": rep["failed"]})
            self._changed(state, "analyst assessment changed")
            self._save(state); return state

    async def rerun_reasoning(self, case_id):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            previous = state.status
            state.status = "running"; self._save(state)       # blocks other mutations meanwhile
        try:
            await self._reason(state)
            self._ledger(state, "REASONING_RERUN", {"bob": {k: v.get("provider") for k, v in state.bob.items()}})
        finally:
            state.status = previous
            self._after_change(state, why="reasoning re-run")
        return state

    def paste_bob_reply(self, case_id, mode, reply, officer):
        """Manual mode (plan §8.8): a reply the officer obtained from Bob goes through the same validation."""
        if mode not in ("hypothesis-assessor", "skeptic", "risk-assessor", "legal-proposer"):
            raise CaseError(422, "manual replies are accepted for hypothesis-assessor, skeptic, risk-assessor, legal-proposer")
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            od = self._obs_dicts(state); ids = {o["observation_id"] for o in od}
            groups = reasoning.groups_of(od)
            extra = {"hypothesis-assessor": reasoning.ach_validator(set(groups)),
                     "skeptic": reasoning.obs_validator(ids, "challenges"),
                     "risk-assessor": reasoning.risk_validator(ids),
                     "legal-proposer": reasoning.legal_validator(set(self.rules.get_all_keys()))}[mode]
            try:
                data = self.bob.validate(reply, reasoning.SCHEMAS[mode], extra)
            except Exception as e:
                raise CaseError(422, f"reply rejected by validator: {e}")
            path = self.store.case_dir(case_id) / "artifacts" / f"bob_{mode}_manual_{new_id('RAW')}.json"
            path.write_text(json.dumps({"mode": mode, "pasted_by": officer, "reply": reply, "parsed": data}, indent=2,
                                       ensure_ascii=False), encoding="utf-8")
            state.bob[mode] = {"provider": "bob-manual", "status": "ok", "error": None, "artifact": path.name,
                               "sha256": sha256_file(path), "at": utcnow(), "pasted_by": officer}
            self._ledger(state, "AGENT_RUN", {"mode": mode, "provider": "bob-manual", "sha256": state.bob[mode]["sha256"],
                                              "pasted_by": officer})
            if mode == "hypothesis-assessor":
                props = dict(state.ach.get("proposals") or {})
                for c in data["cells"]:
                    props.setdefault(c["group_id"], {})[c["hypothesis_id"]] = {"value": c["value"], "reason": c["reason"],
                                                                              "proposed_by": "bob-manual"}
                state.ach = {**state.ach, "proposals": props, "assessor": "bob-manual"}
            elif mode == "skeptic":
                state.challenges = [{**c, "provider": "bob-manual"} for c in data["challenges"]]
            elif mode == "risk-assessor":
                state.triage = {**data, "provider": "bob-manual", "generated_utc": utcnow(),
                                "deterministic_risk_score": state.risk.get("risk_score"),
                                "deterministic_band": state.risk.get("band"),
                                "policy": (state.triage or {}).get("policy")}
            else:
                facts = state.legal.get("facts") or {}
                state.legal.update(proposals=data["circumstances"], proposed_by="bob-manual", status="proposed",
                                   results=[r.to_dict() for r in self.rules.evaluate_multiple(
                                       [c["circumstance_key"] for c in data["circumstances"]], facts)])
            return self._after_change(state, invalidate_ach=(mode == "hypothesis-assessor"))

    # ================================================================ reports
    def _draft_brief(self, state) -> dict:
        det = reporting.deterministic_brief(state)
        keys = set(reporting.SECTION_TITLES)
        def sections_ok(d):
            bad = [s["key"] for s in d["sections"] if s["key"] not in keys]
            if bad: raise ValueError(f"unknown section keys {bad}")
        payload = {"draft": det, "rules": "Keep every citation. Every evidence sentence must cite [OBS-…] or [RULE-…]. "
                                          "No percentages, no probabilities, no verdict words."}
        rec = self._bob(state, "drafter-brief", payload, lambda: det, sections_ok)
        brief = reporting.assemble_brief(state, rec["response"], rec["provider"])
        tries = 0
        while rec["status"] == "ok" and brief["unsupported_sentences"] and tries < 2:
            tries += 1
            failed = [r for s in brief["sections"] for r in s["results"] if not r["passed"] and s["key"] != "analyst"]
            if not failed: break
            payload = {"draft": rec["response"], "rejected_sentences": failed}
            rec = self._bob(state, "drafter-brief", payload, lambda: det, sections_ok)
            brief = reporting.assemble_brief(state, rec["response"], rec["provider"])
        # Entailment half of the Verifier (Bob); deterministic half already applied.
        evid = [(si, ri, r) for si, s in enumerate(brief["sections"]) if s["key"] in reporting.EVIDENCE_SECTIONS
                for ri, r in enumerate(s["results"]) if r["passed"]]
        if evid:
            obs = {o.observation_id: reasoning.obs_for_bob(o.model_dump()) for o in state.observations}
            vp = {"sentences": [{"sentence_index": n, "sentence": r["sentence"],
                                 "cited": [obs.get(c) or c for c in r["cited_ids"]]} for n, (_, _, r) in enumerate(evid)]}
            vrec = self._bob(state, "verifier", vp,
                             lambda: {"results": [{"sentence_index": n, "result": "pass",
                                                   "reason": "entailment not checked (Bob unavailable); deterministic "
                                                             "citation check passed", "weaker_rewrite": None}
                                                  for n in range(len(evid))]})
            for v in vrec["response"]["results"]:
                if v["result"] == "fail" and 0 <= v["sentence_index"] < len(evid):
                    si, ri, r = evid[v["sentence_index"]]
                    r["passed"] = False
                    r["problems"].append(f"entailment: {v['reason']}" +
                                         (f" (suggested: {v['weaker_rewrite']})" if v.get("weaker_rewrite") else ""))
            brief["entailment_checked_by"] = vrec["provider"]
            brief["unsupported_sentences"] = sum(1 for s in brief["sections"] for r in s["results"] if not r["passed"])
        return brief

    def _write_package(self, state, out: Path, footer: dict | None) -> dict:
        out.mkdir(parents=True, exist_ok=True)
        led = self.store.ledger(state.case_id)
        lv = led.verify()
        brief = self._draft_brief(state)
        state.brief = brief
        (out / "investigation_brief.md").write_text(reporting.render_brief_md(state, brief, footer), encoding="utf-8")
        (out / "brief_verification.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "evidence_matrix.csv").write_text(reporting.evidence_matrix_csv(state), encoding="utf-8")
        tools = [{"tool_name": t["name"], "tool_version": t["version"]}
                 for aid, _, _ in AGENTS for t in (envelope.tool_info(n) for n in envelope.AGENT_TOOLS.get(aid, []))
                 if t.get("available")]
        reverified = intake.verify(Path(state.original.path), state.original.sha256)
        cert_json, cert_txt = reporting.certificate(
            state, self._custody(state).to_report_section(state.evidence_id),
            {"chain_verified": lv["valid"], "ledger_head": lv.get("head"), "total_entries": lv["entries"]},
            tools, reverified, out)
        guides = reporting.victim_guides(state, out)
        (out / "triage_internal.json").write_text(json.dumps({"risk_index": state.risk, "triage": state.triage},
                                                             indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "technical_report.md").write_text(reporting.technical_markdown(state, lv), encoding="utf-8")
        export = {"schema_version": "EMAFIG-EVIDENCE-2.0", "generated_utc": utcnow(), "case": state.model_dump(),
                  "baseline_profile": baselines.profile_table(), "ledger": lv,
                  "limitations": ["Automated screening is not a binary truth detector.",
                                  "Baselines are uncalibrated heuristic defaults.",
                                  "Triage probability is an uncalibrated estimate for internal prioritisation only.",
                                  "Legal mapping is decision support and requires legal-officer confirmation."]}
        (out / "forensic_package.json").write_text(json.dumps(export, indent=2, default=str, ensure_ascii=False),
                                                   encoding="utf-8")
        files = sorted(p for p in out.iterdir() if p.is_file() and p.name not in ("package_manifest.json", "SEAL.json"))
        manifest = {"case_id": state.case_id, "generated_utc": utcnow(), "ledger_head_at_generation": lv.get("head"),
                    "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files]}
        manifest["report_hash"] = sha256_bytes(canonical(manifest["files"]).encode())
        (out / "package_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        state.reports = {"dir": str(out), "brief": str(out / "investigation_brief.md"),
                         "markdown": str(out / "technical_report.md"), "json": str(out / "forensic_package.json"),
                         "certificate": str(cert_txt), "certificate_json": str(cert_json),
                         "evidence_matrix": str(out / "evidence_matrix.csv"), "triage": str(out / "triage_internal.json"),
                         "manifest": str(out / "package_manifest.json"),
                         **{f"victim_guide_{g['code']}": g["path"] for g in guides}}
        state.human_review["victim_guides"] = [{k: v for k, v in g.items() if k != "path"} for g in guides]
        return manifest

    def generate_report(self, case_id, signoff: dict | None = None):
        if signoff:   # backwards-compatible single call used by older clients
            return self.signoff(case_id, signoff.get("reviewer", "investigator"), signoff.get("role", "officer"),
                                signoff.get("statement", ""))
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            if state.signoffs:
                self._changed(state, "draft regenerated")
            state.limitations = self._limitations(state)
            n = len([p for p in (self.store.case_dir(case_id) / "reports").glob("draft-*")]) + 1
            manifest = self._write_package(state, self.store.case_dir(case_id) / "reports" / f"draft-{n:03d}", None)
            state.status = "awaiting_signoff"
            state.stage = "signoff"
            state.human_review["report_stale"] = False
            self._ledger(state, "REPORT_GENERATED", {"version": f"draft-{n:03d}", "report_hash": manifest["report_hash"],
                                                     "files": manifest["files"],
                                                     "unsupported_sentences": state.brief["unsupported_sentences"]})
            self._save(state); return state

    def signoff(self, case_id, reviewer, role, statement):
        with self.store.case_lock(case_id):
            state = self._mutable(case_id)
            if not statement.strip(): raise CaseError(422, "a non-empty sign-off statement is required")
            if not state.reports: raise CaseError(409, "generate the draft report before sign-off")
            if state.human_review.get("report_stale"):
                raise CaseError(409, "the case changed after the draft was generated; regenerate the report first")
            gates = []
            if not any(o.review_status == "accepted" for o in state.observations):
                gates.append("S5: no confirmed observation")
            if not state.ach.get("accepted_by"): gates.append("S7: ACH matrix not accepted by an analyst")
            if not state.legal.get("confirmed_by"): gates.append("S9: legal circumstances not confirmed by an officer")
            if gates: raise CaseError(409, "sign-off blocked — " + "; ".join(gates))
            others = [s for s in state.signoffs if s["role"] != role]
            if any(s["reviewer"] == reviewer for s in others):
                raise CaseError(409, "officer and supervisor sign-offs must come from two different people")
            state.signoffs = others + [{"role": role, "reviewer": reviewer, "statement": statement, "at": utcnow(),
                                        "unsupported_sentences_at_signoff": (state.brief or {}).get("unsupported_sentences")}]
            self._ledger(state, "HUMAN_SIGNOFF", state.signoffs[-1])
            state.human_review["signoff"] = state.signoffs[-1]
            if {s["role"] for s in state.signoffs} >= {"officer", "supervisor"}:
                self._finalise(state)
            else:
                state.status = "awaiting_second_signoff"
            self._save(state); return state

    def _finalise(self, state):
        out = self.store.case_dir(state.case_id) / "reports" / "final"
        footer = {"signoffs": state.signoffs, "ledger_head": self.store.ledger(state.case_id).head()}
        manifest = self._write_package(state, out, footer)
        officer = next(s for s in state.signoffs if s["role"] == "officer")
        self._custody_event(state, "export", actor_id=officer["reviewer"], actor_name=officer["reviewer"],
                            reason=f"final package, report hash {manifest['report_hash']}")
        self._ledger(state, "REPORT_FINAL", {"report_hash": manifest["report_hash"], "files": manifest["files"]})
        seal = self._ledger(state, "LEDGER_SEALED", {"report_hash": manifest["report_hash"],
                                                     "sealed_by": [s["reviewer"] for s in state.signoffs]})
        (out / "SEAL.json").write_text(json.dumps({"seal_entry": seal, "final_ledger_head": seal["hash"],
                                                   "report_hash": manifest["report_hash"]}, indent=2), encoding="utf-8")
        state.reports["seal"] = str(out / "SEAL.json")
        state.ledger.update(final_head=seal["hash"], report_hash=manifest["report_hash"])
        state.sealed = True; state.status = "complete"; state.stage = "sealed"
