"""
app/reasoning.py
Plane B contracts (JSON schemas per Bob mode), data-minimised payloads, the
deterministic fallbacks used when Bob is unavailable, and the ACH /
contradiction logic built on core.plane_c.

Nothing here decides guilt or authenticity. ACH output is a matrix and a
ranking; the only number resembling a probability is produced by the
risk-assessor mode and is always labelled as an uncalibrated triage estimate.
"""
from __future__ import annotations

from typing import Any

from core.plane_c.ach import ACHMatrix, DEFAULT_HYPOTHESES, rank_hypotheses, find_non_diagnostic_rows
from core.plane_c.independence import get_family

HYP_IDS = [h["id"] for h in DEFAULT_HYPOTHESES]
HYP_DESCRIPTIONS = {
    "H1": "The media is an unaltered capture of what it appears to show.",
    "H2": "Face or content was altered after capture (face swap, reenactment, edit).",
    "H3": "The media was generated or substantially synthesised.",
    "H4": "Authentic capture whose anomalies come from benign processing (platform recompression, legitimate edit).",
    "H5": "Manipulated content that was subsequently re-encoded or redistributed.",
    "H6": "Only the audio was manipulated (voice clone or splice over genuine video).",
    "H7": "Screen recording of a live or real-time deepfake call.",
}

# --------------------------------------------------------------------------
# Output schemas (one per Bob mode)
# --------------------------------------------------------------------------
_CELL = {"type": "object", "required": ["group_id", "hypothesis_id", "value", "reason"],
         "properties": {"group_id": {"type": "string"}, "hypothesis_id": {"type": "string", "pattern": "^H\\d+$"},
                        "value": {"enum": ["C", "I", "N"]}, "reason": {"type": "string", "maxLength": 400}}}

SCHEMAS: dict[str, dict] = {
    "hypothesis-assessor": {"type": "object", "required": ["cells"],
                            "properties": {"cells": {"type": "array", "items": _CELL},
                                           "notes": {"type": "string"}}},
    "skeptic": {"type": "object", "required": ["challenges"], "properties": {"challenges": {"type": "array", "items": {
        "type": "object", "required": ["observation_id", "alternatives"],
        "properties": {"observation_id": {"type": "string"}, "no_alternative_found": {"type": "boolean"},
                       "alternatives": {"type": "array", "items": {
                           "type": "object", "required": ["explanation", "discriminating_test", "test_run"],
                           "properties": {"explanation": {"type": "string"}, "discriminating_test": {"type": "string"},
                                          "test_run": {"type": "boolean"},
                                          "artifact": {"type": ["string", "null"]}}}}}}}}},
    "legal-proposer": {"type": "object", "required": ["circumstances"], "properties": {"circumstances": {
        "type": "array", "items": {"type": "object", "required": ["circumstance_key", "reasoning"],
                                   "properties": {"circumstance_key": {"type": "string"},
                                                  "reasoning": {"type": "string"},
                                                  "wording_concern": {"type": ["string", "null"]}}}}}},
    "risk-assessor": {"type": "object",
                      "required": ["likelihood_band", "probability_manipulated", "probability_label", "reasoning",
                                   "key_observations", "counter_indicators", "estimate_confidence"],
                      "properties": {
                          "likelihood_band": {"enum": ["low", "moderate", "high"]},
                          "probability_manipulated": {"type": "number", "minimum": 0, "maximum": 1},
                          "probability_label": {"enum": ["llm_estimate_uncalibrated", "heuristic_from_risk_index"]},
                          "reasoning": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                          "key_observations": {"type": "array", "items": {"type": "string"}},
                          "counter_indicators": {"type": "array", "items": {"type": "string"}},
                          "baseline_deviations_considered": {"type": "array", "items": {"type": "string"}},
                          "estimate_confidence": {"enum": ["low", "medium", "high"]}}},
    "drafter-brief": {"type": "object", "required": ["sections"], "properties": {"sections": {"type": "array", "items": {
        "type": "object", "required": ["key", "sentences"],
        "properties": {"key": {"type": "string"}, "sentences": {"type": "array", "items": {"type": "string"}}}}}}},
    "verifier": {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {
        "type": "object", "required": ["sentence_index", "result", "reason"],
        "properties": {"sentence_index": {"type": "integer"}, "result": {"enum": ["pass", "fail"]},
                       "reason": {"type": "string"}, "weaker_rewrite": {"type": ["string", "null"]}}}}}},
}

# --------------------------------------------------------------------------
# Data minimisation (plan §8.5): no media, no paths, no filenames, no identifiers
# --------------------------------------------------------------------------

def _clean(v: Any, depth: int = 0) -> Any:
    if isinstance(v, dict):
        return {k: _clean(x, depth + 1) for k, x in v.items()
                if "path" not in k.lower() and k not in {"filename", "sender_id", "spike_indices", "anomaly_indices",
                                                         "irregular_gops", "raw_output"}}
    if isinstance(v, list):
        return [_clean(x, depth + 1) for x in v[:20]]
    if isinstance(v, str):
        return v[:300]
    return v


def obs_for_bob(o: dict) -> dict:
    b = o.get("baseline") or {}
    return {"observation_id": o["observation_id"], "type": o["type"], "agent": o["agent_id"],
            "statement": o["statement"][:400], "measurement": _clean(o.get("measurement", {})),
            "location": _clean(o.get("location", {})), "independence_group": o.get("independence_group"),
            "baseline": {k: b.get(k) for k in ("check_id", "metric", "value", "normal_range", "level", "reason",
                                              "calibrated")},
            "alternatives": o.get("alternative_explanations", []), "limitations": o.get("limitations", [])[:4],
            "review_status": o.get("review_status")}


def active(observations: list[dict]) -> list[dict]:
    return [o for o in observations if o.get("review_status") != "rejected"]


def groups_of(observations: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    for o in active(observations):
        g.setdefault(o["independence_group"], []).append(o)
    return g


def group_summary(gid: str, members: list[dict]) -> dict:
    driver = max(members, key=lambda o: (o.get("baseline") or {}).get("points", 0.0))
    b = driver.get("baseline") or {}
    return {"group_id": gid, "family": gid.split(":", 1)[-1], "observation_ids": [o["observation_id"] for o in members],
            "driver": driver["observation_id"], "level": b.get("level"), "points": b.get("points", 0.0),
            "supports": b.get("supports", []), "reason": b.get("reason"),
            "confirmed": any(o.get("review_status") == "accepted" for o in members)}

# --------------------------------------------------------------------------
# Fallbacks
# --------------------------------------------------------------------------
_FLAGGED_CELLS: dict[str, dict[str, str]] = {
    # "I*" = I only when the group's baseline level is high, otherwise C.
    "face_boundary": {"H1": "I*", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "N", "H7": "C"},
    "av_sync":       {"H1": "I*", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "C", "H7": "C"},
    "temporal":      {"H1": "I*", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "N", "H7": "C"},
    "audio_splice":  {"H1": "I*", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "C", "H7": "C"},
    "frequency":     {"H1": "I*", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "N", "H7": "C"},
    "recompression": {"H1": "C", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "N", "H7": "C"},
    "sharpness":     {"H1": "C", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "N", "H7": "C"},
}
_GENERATOR_CELLS = {"H1": "I", "H2": "C", "H3": "C", "H4": "I", "H5": "C", "H6": "N", "H7": "N"}
_EDITOR_CELLS = {"H1": "I", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "C", "H7": "N"}
_C2PA_INVALID = {"H1": "I", "H2": "C", "H3": "C", "H4": "C", "H5": "C", "H6": "C", "H7": "C"}


def fallback_ach(groups: dict[str, list[dict]]) -> dict:
    cells = []
    for gid, members in groups.items():
        s = group_summary(gid, members)
        fam, pts, lvl = s["family"], s["points"] or 0.0, s["level"]
        if pts <= 0:
            row = {h: "C" for h in HYP_IDS}
            why = "No deviation from the built-in baseline; consistent with every hypothesis (non-diagnostic)."
        elif fam == "metadata_software":
            row = _GENERATOR_CELLS if pts >= 1.0 else (_EDITOR_CELLS if pts >= 0.5 else {h: "C" for h in HYP_IDS})
            why = s["reason"] or "software tag"
        elif fam == "provenance":
            row = _GENERATOR_CELLS if pts >= 1.0 else _C2PA_INVALID
            why = s["reason"] or "C2PA state"
        else:
            tmpl = _FLAGGED_CELLS.get(fam, {h: "C" for h in HYP_IDS})
            row = {h: ("I" if lvl == "high" else "C") if v == "I*" else v for h, v in tmpl.items()}
            why = f"Baseline level {lvl}: {s['reason']}"
        for h in HYP_IDS:
            v = row.get(h, "C")
            reason = (why if v != "I" else f"Inconsistent: {why}") if v != "N" else "Not applicable to this modality."
            cells.append({"group_id": gid, "hypothesis_id": h, "value": v, "reason": reason[:400]})
    return {"cells": cells, "notes": "Rule-based fallback proposals; the analyst must review every cell."}


_TESTS = [
    (("recompress", "transcod", "platform", "compression", "quantiz", "resav", "re-encod"),
     "Compare against an earlier-generation or platform-original copy, and run the benign-transform control "
     "(pass a known-genuine clip through the same platform and re-measure)."),
    (("resiz", "rescal", "upscal"), "Check native resolution against the claimed device and look for resampling traces."),
    (("focus", "blur", "motion"), "Inspect neighbouring frames for optical blur consistent with camera or subject motion."),
    (("light", "vignett", "shadow"), "Compare lighting direction and shadows on the face and background."),
    (("variable frame", "vfr", "container", "mux", "timestamp", "decoder"),
     "Re-check per-frame timestamps and confirm whether the device records variable frame rate."),
    (("edit", "trim", "scene", "cut", "concaten"), "Obtain the edit history or the original; check for scene cuts at the flagged frames."),
    (("speech", "consonant", "background", "noise"),
     "Listen to the flagged intervals and mark spikes that coincide with plosives or background events."),
    (("codec", "channel"), "Decode with a second decoder and compare the measurement."),
    (("domain shift", "unseen", "non-speech"), "Obtain a verified reference recording of the speaker for comparison."),
    (("occlusion", "pose", "resolution", "mask", "glasses", "profile"), "Re-run face detection on frames with a frontal, unoccluded view."),
    (("strip", "unsupported", "capture device"), "Ask the source platform or device owner for the original file."),
    (("screen record",), "Check for screen-capture UI elements, cursor, or refresh-rate aliasing."),
]


def _test_for(alt: str) -> str:
    a = alt.lower()
    for keys, test in _TESTS:
        if any(k in a for k in keys):
            return test
    return "Obtain the original file or an independent copy and repeat the measurement."


def fallback_skeptic(observations: list[dict]) -> dict:
    out = []
    for o in active(observations):
        b = o.get("baseline") or {}
        if b.get("points", 0) <= 0 and o.get("review_status") != "accepted":
            continue
        alts = o.get("alternative_explanations") or []
        out.append({"observation_id": o["observation_id"], "no_alternative_found": not alts,
                    "alternatives": [{"explanation": a, "discriminating_test": _test_for(a), "test_run": False,
                                      "artifact": None} for a in alts]})
    return {"challenges": out}


def fallback_legal(facts: dict, engine) -> dict:
    out = []
    for r in engine.evaluate_all(facts):
        if r.applicable:
            out.append({"circumstance_key": r.key,
                        "reasoning": ("Always applicable to electronic evidence." if not engine.get_rule(r.key).get("preconditions")
                                      else "Preconditions met by officer-entered facts: " +
                                      ", ".join(f"{k}={facts.get(k)}" for k in engine.get_rule(r.key)["preconditions"])),
                        "wording_concern": "; ".join(r.gender_warnings) or None})
    return {"circumstances": out}


def fallback_risk(risk: dict, observations: list[dict]) -> dict:
    score = risk.get("risk_score", 0)
    contrib = risk.get("contributions", [])
    counters = [f"{o['observation_id']} ({o['type']}) within baseline"
                for o in active(observations)
                if (o.get("baseline") or {}).get("level") == "within" and (o.get("baseline") or {}).get("family_weight", 0) > 0]
    return {
        "likelihood_band": risk.get("band", "low"),
        "probability_manipulated": round(0.05 + 0.9 * score / 100.0, 2),
        "probability_label": "heuristic_from_risk_index",
        "reasoning": ([f"Deterministic mapping of the uncalibrated risk index ({score}/100); Bob was not consulted."] +
                      [f"{c['family']}: {c.get('reason')} (contribution {c['contribution']})" for c in contrib[:5]]),
        "key_observations": [c["driver"] for c in contrib[:5] if c.get("driver")],
        "counter_indicators": counters[:10],
        "baseline_deviations_considered": [c["group_id"] for c in contrib],
        "estimate_confidence": "low",
    }

# --------------------------------------------------------------------------
# Validators that need case context
# --------------------------------------------------------------------------

def ach_validator(group_ids: set[str]):
    def check(data):
        bad = [c["group_id"] for c in data["cells"] if c["group_id"] not in group_ids]
        if bad: raise ValueError(f"unknown group_id(s): {sorted(set(bad))[:5]}")
        badh = [c["hypothesis_id"] for c in data["cells"] if c["hypothesis_id"] not in HYP_IDS]
        if badh: raise ValueError(f"unknown hypothesis id(s): {sorted(set(badh))}")
    return check


def obs_validator(obs_ids: set[str], key: str, field: str = "observation_id"):
    def check(data):
        bad = [x[field] for x in data[key] if x[field] not in obs_ids]
        if bad: raise ValueError(f"unknown observation id(s): {bad[:5]}")
    return check


def risk_validator(obs_ids: set[str]):
    def check(data):
        bad = [x for x in data["key_observations"] if x not in obs_ids]
        if bad: raise ValueError(f"unknown observation id(s) in key_observations: {bad[:5]}")
        if data["probability_label"] != "llm_estimate_uncalibrated":
            raise ValueError("probability_label must be 'llm_estimate_uncalibrated' for a Bob estimate")
    return check


def legal_validator(keys: set[str]):
    def check(data):
        bad = [c["circumstance_key"] for c in data["circumstances"] if c["circumstance_key"] not in keys]
        if bad: raise ValueError(f"circumstance keys not in the rules table: {bad}")
    return check

# --------------------------------------------------------------------------
# ACH assembly
# --------------------------------------------------------------------------

def build_ach(groups: dict[str, list[dict]], proposals: dict, edits: dict) -> dict:
    """proposals/edits: {group_id: {H: {value, reason, proposed_by}}}. Returns the stored ACH view."""
    full, confirmed = ACHMatrix(), ACHMatrix()
    rows = []
    for gid, members in sorted(groups.items()):
        s = group_summary(gid, members)
        row = {}
        for h in HYP_IDS:
            cell = (edits.get(gid, {}).get(h) or proposals.get(gid, {}).get(h)
                    or {"value": "N", "reason": "no proposal", "proposed_by": "none"})
            row[h] = cell
            full.set_cell(gid, h, cell["value"], cell.get("reason", ""), cell.get("proposed_by", "hypothesis-assessor"))
            if s["confirmed"]:
                confirmed.set_cell(gid, h, cell["value"], cell.get("reason", ""), cell.get("proposed_by", "hypothesis-assessor"))
        rows.append({**s, "cells": row})
    nd = find_non_diagnostic_rows(full)
    for r in rows:
        r["diagnostic"] = r["group_id"] not in nd
        r["provisional"] = not r["confirmed"]
    return {"hypotheses": [{**h, "description": HYP_DESCRIPTIONS[h["id"]]} for h in DEFAULT_HYPOTHESES],
            "rows": rows, "ranking_provisional": rank_hypotheses(full),
            "ranking_confirmed": rank_hypotheses(confirmed) if confirmed.cells else None,
            "rule": "Rank by fewest I cells across diagnostic rows. Output is a ranking, never a probability."}


def contradictions_from_ach(ach: dict) -> list[dict]:
    out = []
    diag = [r for r in ach["rows"] if r["diagnostic"]]
    for h in HYP_IDS:
        cons = [r for r in diag if r["cells"][h]["value"] == "C" and r["points"] > 0]
        inc = [r for r in diag if r["cells"][h]["value"] == "I"]
        if cons and inc:
            out.append({"hypothesis_id": h,
                        "consistent_groups": [r["group_id"] for r in cons],
                        "inconsistent_groups": [r["group_id"] for r in inc],
                        "support": [o for r in cons for o in r["observation_ids"]],
                        "contradiction": [o for r in inc for o in r["observation_ids"]],
                        "status": "unresolved"})
    return out


def family_of(obs_type: str) -> str:
    return get_family(obs_type)
