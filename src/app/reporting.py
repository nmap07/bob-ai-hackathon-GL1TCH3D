"""
app/reporting.py
Outputs (plan §11): evidence-bound investigation brief with the Verifier,
evidence matrix, BSA 2023 s.63(4) certificate draft, victim guides, and the
technical report.

Policy: the risk index and any probability are triage aids for the officer.
They appear only in the clearly-marked internal triage annex and JSON, never
in the investigation brief or the certificate; the Verifier keeps rejecting
percentages and verdict language in the brief.
"""
from __future__ import annotations

import csv, io, json, os
from pathlib import Path

from core.plane_c.certificate import CertificateGenerator
from core.plane_c.citation_check import CitationChecker
from core.plane_c.legal_engine import LegalRulesEngine, RULES_TABLE_VERSION

from app.reasoning import HYP_IDS

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates" / "victim_guide"
RULES = LegalRulesEngine()

EVIDENCE_SECTIONS = ("findings", "ach", "challenges", "legal", "analyst")
SECTION_TITLES = {
    "case": "1. Case information and evidence identification",
    "tools": "2. Tools and versions",
    "media": "3. Media characteristics",
    "findings": "4. Findings (analyst-confirmed observations only)",
    "ach": "5. Independence groups and ACH ranking",
    "challenges": "6. Anticipated challenges",
    "gaps": "7. Missing evidence and recommended collection",
    "legal": "8. Legal mapping (candidate provisions; legal-officer confirmation required)",
    "limitations": "9. Limitations",
    "analyst": "10. Analyst assessment",
}
VICTIM_LANGS = {"en": "English", "hi": "Hindi"}
VICTIM_REVIEW = {"en": "Template requires review by a victim-support professional before first use.",
                 "hi": "DRAFT TRANSLATION: requires native-speaker and victim-support review before use."}


def _review_map(s: str) -> str:
    return {"accepted": "confirmed", "rejected": "rejected"}.get(s, "pending")


def checker(state) -> CitationChecker:
    obs = [{"obs_id": o.observation_id, "review": {"status": _review_map(o.review_status)}} for o in state.observations]
    return CitationChecker(obs, RULES.get_all_section_ids(), artifact_ids={state.original.artifact_id},
                           require_confirmed=True)


def verify_sentences(state, sentences: list[str]) -> list[dict]:
    rep = checker(state).check_draft(sentences)
    return [r.to_dict() for r in rep.results]


def verify_text(state, text: str) -> dict:
    return checker(state).check_text(text).to_dict()

# --------------------------------------------------------------------------
# Deterministic brief (also the drafter fallback)
# --------------------------------------------------------------------------

def _cite(ids): return "".join(f"[{i}]" for i in ids)


def deterministic_brief(state) -> dict:
    s: dict[str, list[str]] = {k: [] for k in SECTION_TITLES}
    it = state.intake
    accepted = [o for o in state.observations if o.review_status == "accepted"]

    s["case"] += [
        f"Case {state.case_id}, evidence {state.evidence_id}, received "
        f"{it.received_at or 'at an unrecorded time'} via {it.how_received or 'an unrecorded method'}"
        f"{' on ' + it.platform if it.platform else ''}.",
        f"SHA-256 of the preserved original [{state.original.artifact_id}]: {state.original.sha256}.",
        f"Original stored read-only: {'yes' if state.original.read_only else 'NO (file system did not allow it)'}; "
        f"hash re-verified before analysis: {state.ledger.get('source_reverified', 'not recorded')}.",
    ]
    if it.source_url: s["case"].append(f"Source URL recorded at intake: {it.source_url}.")
    for aid, ar in state.agent_runs.items():
        s["tools"].append(f"{aid} v{ar.version}: {ar.status}.")
    s["media"].append(f"Media type {state.media_type}, {state.original.size_bytes} bytes.")
    for o in state.observations:
        if o.type in ("metadata.container", "metadata.video_codec", "metadata.resolution", "metadata.duration_seconds",
                      "metadata.audio_codec", "visual.image_dimensions") and o.review_status != "rejected":
            s["media"].append(o.statement)

    for o in accepted:
        b = o.baseline or {}
        if b.get("level") in ("within", "elevated", "high"):
            s["findings"].append(f"{o.statement.rstrip('.')}; baseline {b.get('check_id')} gives level "
                                 f"'{b.get('level')}' ({b.get('reason')}); this is an uncalibrated indicator {_cite([o.observation_id])}.")
        else:
            s["findings"].append(f"{o.statement.rstrip('.')}; recorded as context, not scored against a baseline "
                                 f"{_cite([o.observation_id])}.")
    if not accepted:
        s["limitations"].append("No finding has been confirmed by an analyst, so this brief relies on none of them.")

    rank = (state.ach or {}).get("ranking_confirmed")
    rows = [r for r in (state.ach or {}).get("rows", []) if r["confirmed"]]
    if rank and rows:
        acc = {o.observation_id for o in accepted}
        diag = [r for r in rows if r["diagnostic"]]
        if not diag:
            ids = [i for r in rows for i in r["observation_ids"] if i in acc]
            s["ach"].append(f"Every confirmed line of evidence is consistent with all seven hypotheses, so none of "
                            f"them discriminates between hypotheses {_cite(ids[:6])}.")
        else:
            sc = rank["scores"]; lo = min(sc.values()); hi = max(sc.values())
            ids = [i for r in diag for i in r["observation_ids"] if i in acc]
            s["ach"].append(f"Across {len(diag)} diagnostic line(s) of evidence, "
                            f"{', '.join(h for h in HYP_IDS if sc[h] == lo)} show the fewest inconsistencies ({lo}) and "
                            f"{', '.join(h for h in HYP_IDS if sc[h] == hi)} the most ({hi}) {_cite(ids[:6])}.")
            for r in diag:
                inc = [h for h in HYP_IDS if r["cells"][h]["value"] == "I"]
                con = [h for h in HYP_IDS if r["cells"][h]["value"] == "C"]
                s["ach"].append(f"The {r['family']} line of evidence is inconsistent with {', '.join(inc) or 'no hypothesis'} "
                                f"and consistent with {', '.join(con) or 'no hypothesis'} "
                                f"{_cite([i for i in r['observation_ids'] if i in acc])}.")
            s["ach"].append(f"This ranking compares consistency between hypotheses and is not a probability "
                            f"{_cite(ids[:3])}.")
    else:
        s["limitations"].append("No ACH ranking over confirmed observations is available.")
    if not (state.ach or {}).get("accepted_by"):
        s["limitations"].append("The ACH matrix has not yet been accepted by an analyst.")

    acc_ids = {o.observation_id for o in accepted}
    for ch in state.challenges:
        if ch["observation_id"] not in acc_ids:
            continue
        for alt in ch.get("alternatives", [])[:3]:
            status = "has been run" if alt.get("test_run") else "has not been run, so this alternative is unresolved"
            s["challenges"].append(f"For [{ch['observation_id']}], {alt['explanation']} could produce a similar "
                                   f"measurement; the discriminating test ({alt['discriminating_test'].rstrip('.')}) {status}.")

    for g in state.missing_evidence:
        if g.get("kind") == "checklist" and g.get("status") in ("missing", "unavailable"):
            s["gaps"].append(f"{g['label']} ({g['status']}): {g['action']}.")
        elif g.get("kind") == "pipeline":
            s["gaps"].append(f"Pipeline gap: {g['item']} ({g['status']}).")

    legal = state.legal or {}
    if legal.get("confirmed_by"):
        for r in legal.get("results", []):
            if not r["applicable"]:
                continue
            rid = f"RULE-{r['key']}"
            kept = [x for x in r["sections"] if not x.get("excluded")]
            if kept:
                provisions = "; ".join("{} {} ({}, {})".format(x["act"], x["section"], x["title"], x["status"])
                                       for x in kept)
                needed = ", ".join(r["evidence_needed"]) or "none listed"
                s["legal"].append(f"Circumstance '{r['label']}' may be relevant; candidate provisions {provisions}; "
                                  f"evidence still needed: {needed} [{rid}].")
            for x in r["sections"]:
                if x.get("excluded"):
                    s["legal"].append(f"{x['act']} section {x['section']} is not proposed: {x['exclusion_reason']} [{rid}].")
            if r.get("escalation_required"):
                s["legal"].append(f"Escalation required: {r['notes']} [{rid}]")
    else:
        s["limitations"].append("Legal circumstances have not been confirmed by an officer; no provisions are listed.")

    for aid, ar in state.agent_runs.items():
        if ar.status == "failed":
            s["limitations"].append(f"{aid} failed ({ar.error}); its evidence channel is unavailable.")
        elif ar.status == "not_applicable":
            s["limitations"].append(f"{aid} was not applicable to {state.media_type} evidence.")
    s["limitations"] += list(state.limitations)
    s["limitations"] += [
        "Baselines are built-in heuristic defaults, not calibrated on a labelled reference population.",
        "By policy the triage risk index and any probability estimate are excluded from this brief.",
        "Absence of C2PA provenance or metadata is recorded as a gap, not as evidence of manipulation.",
    ]
    return {"sections": [{"key": k, "sentences": v} for k, v in s.items() if k != "analyst"]}


def assemble_brief(state, draft: dict, provider: str) -> dict:
    """Attach verifier results (evidence sections) to a draft and add the analyst assessment."""
    sections = []
    for sec in draft["sections"]:
        if sec["key"] not in SECTION_TITLES or sec["key"] == "analyst":
            continue
        sentences = sec["sentences"]
        results = verify_sentences(state, sentences) if sec["key"] in EVIDENCE_SECTIONS else \
            [{"index": i, "sentence": x, "passed": True, "problems": [], "cited_ids": [], "context": True}
             for i, x in enumerate(sentences)]
        sections.append({"key": sec["key"], "title": SECTION_TITLES[sec["key"]], "results": results})
    aa = state.analyst_assessment or {}
    if aa.get("text"):
        rep = verify_text(state, aa["text"])
        sections.append({"key": "analyst", "title": SECTION_TITLES["analyst"] + f" — {aa.get('analyst')}",
                         "results": rep["results"]})
    failed = sum(1 for s in sections for r in s["results"] if not r["passed"])
    total = sum(1 for s in sections if s["key"] in EVIDENCE_SECTIONS for _ in s["results"])
    return {"drafted_by": provider, "sections": sections, "unsupported_sentences": failed,
            "evidence_sentences": total}


def render_brief_md(state, brief: dict, footer: dict | None = None) -> str:
    L = [f"# Internal investigation brief — {state.case_id}", "",
         "_Decision support for a cyber-cell investigation. It is not an expert opinion, a verdict, or legal advice. "
         "Every evidence sentence cites an analyst-confirmed observation [OBS-…] or a rules-table entry [RULE-…]._", ""]
    for sec in brief["sections"]:
        L += [f"## {sec['title']}", ""]
        for r in sec["results"]:
            if r["passed"]:
                L.append(f"- {r['sentence']}")
            else:
                L.append(f"- **[UNSUPPORTED — {'; '.join(r['problems'])}]** ~~{r['sentence']}~~")
        if not sec["results"]:
            L.append("- None.")
        L.append("")
    if footer:
        L += ["## 11. Sign-offs and integrity", ""]
        for so in footer.get("signoffs", []):
            L.append(f"- {so['role']}: {so['reviewer']} at {so['at']} — “{so['statement']}”")
        L += [f"- Ledger head at report time: `{footer.get('ledger_head')}`",
              "- Report hash: see `package_manifest.json` (hash of all package files).", ""]
    return "\n".join(L)

# --------------------------------------------------------------------------
# Evidence matrix
# --------------------------------------------------------------------------

def evidence_matrix_csv(state) -> str:
    rows = {r["group_id"]: r for r in (state.ach or {}).get("rows", [])}
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["observation_id", "evidence_location", "observation", "source", "independence_group",
                "baseline_check", "baseline_level", "consistent_with", "inconsistent_with",
                "alternative_explanations", "review"])
    for o in state.observations:
        r = rows.get(o.independence_group or "")
        cons = [h for h in HYP_IDS if r and r["cells"][h]["value"] == "C"] if r else []
        inc = [h for h in HYP_IDS if r and r["cells"][h]["value"] == "I"] if r else []
        w.writerow([o.observation_id, json.dumps(o.location) if o.location else "whole file", o.statement,
                    f"{o.source}:{o.agent_id}", o.independence_group, (o.baseline or {}).get("check_id"),
                    (o.baseline or {}).get("level"), " ".join(cons), " ".join(inc),
                    "; ".join(o.alternative_explanations), o.review_status])
    return buf.getvalue()

# --------------------------------------------------------------------------
# BSA 63(4) certificate draft
# --------------------------------------------------------------------------

def certificate(state, custody_chain: list[dict], ledger_summary: dict, tools: list[dict],
                hash_reverified: bool, out_dir: Path) -> tuple[Path, Path]:
    it = state.intake
    record = {"evidence_id": state.evidence_id, "platform": it.platform, "source_url": it.source_url,
              "how_received": it.how_received, "device_details": it.device_details,
              "seizure_memo_ref": it.seizure_memo_ref,
              "artifact": {"file_name": state.filename, "media_type": state.media_type,
                           "size_bytes": state.original.size_bytes, "created_at": state.created_utc,
                           "sha256": state.original.sha256}}
    derivs = [{"artifact_id": a["artifact_id"], "file_name": a["file_name"], "sha256": a["sha256"],
               "derived_from": state.original.artifact_id, "producer": a["producer"]}
              for a in state.artifacts if a.get("derivative")]
    gen = CertificateGenerator()
    cert = gen.generate(state.case_id, record, custody_chain, ledger_summary, tool_runs=tools,
                        derivatives=derivs, hash_reverified=hash_reverified)
    return gen.save(cert, out_dir)

# --------------------------------------------------------------------------
# Victim guide
# --------------------------------------------------------------------------

def victim_guides(state, out_dir: Path) -> list[dict]:
    fields = {"{case_reference}": state.case_id,
              "{unit_name}": os.getenv("EMAFIG_UNIT_NAME", "[cyber cell name — to be filled by the officer]"),
              "{unit_contact}": os.getenv("EMAFIG_UNIT_CONTACT", "[cyber cell phone/email — to be filled by the officer]")}
    out = []
    for lang, name in VICTIM_LANGS.items():
        tpl = TEMPLATES / f"{lang}.md"
        if not tpl.exists():
            continue
        text = tpl.read_text(encoding="utf-8")
        for k, v in fields.items():
            text = text.replace(k, v)
        p = out_dir / f"victim_guide_{lang}.md"
        p.write_text(text, encoding="utf-8")
        out.append({"language": name, "code": lang, "path": str(p), "review_status": VICTIM_REVIEW[lang]})
    return out

# --------------------------------------------------------------------------
# Technical report
# --------------------------------------------------------------------------

def technical_markdown(state, ledger: dict) -> str:
    c = state
    L = [f"# EMAFIG technical forensic report — {c.case_id}", "",
         "## Evidence identification",
         f"- File: `{c.filename}` ({c.media_type}, {c.original.size_bytes} bytes)",
         f"- Artifact: `{c.original.artifact_id}`; read-only: {c.original.read_only}",
         f"- SHA-256: `{c.original.sha256}`", f"- SHA-512: `{c.original.sha512}`",
         f"- Pipeline run: `{c.pipeline_run_id}`", "",
         "## Intake and preservation"]
    for k, v in c.intake.model_dump().items():
        if v: L.append(f"- {k}: {v}")
    L += ["", "## Agent coverage"]
    for k, v in c.agent_runs.items():
        L.append(f"- **{k}** v{v.version} — {v.status} — {len(v.observation_ids)} obs"
                 + (f" — envelope `{Path(v.envelope_path).name}` sha256 `{v.envelope_sha256[:16]}…`" if v.envelope_path else "")
                 + (f" — error: {v.error}" if v.error else ""))
    L += ["", f"## Observations and baseline checks (profile `{c.baseline_profile}`, uncalibrated)", "",
          "| ID | Type | Value vs baseline | Level | Group | Review |", "|---|---|---|---|---|---|"]
    for o in c.observations:
        b = o.baseline or {}
        L.append(f"| {o.observation_id} | {o.type} | {b.get('value', '')} vs {b.get('normal_range') or '—'} | "
                 f"{b.get('level', '')} | {o.independence_group} | {o.review_status} |")
    L += ["", "## ACH matrix (rows = independence groups)", "",
          "| Group | " + " | ".join(HYP_IDS) + " | Diagnostic |", "|---" * (len(HYP_IDS) + 2) + "|"]
    for r in (c.ach or {}).get("rows", []):
        L.append(f"| {r['group_id']} | " + " | ".join(r["cells"][h]["value"] for h in HYP_IDS)
                 + f" | {'yes' if r['diagnostic'] else 'no (greyed)'} |")
    rp = (c.ach or {}).get("ranking_provisional")
    if rp: L.append(f"\nProvisional ranking (fewest I first): {', '.join(rp['ranking'])}; I-counts {rp['scores']}")
    L += ["", "## Contradictions"] + ([f"- {x['hypothesis_id']}: consistent {x['consistent_groups']} vs inconsistent "
                                       f"{x['inconsistent_groups']} ({x['status']})" for x in c.contradictions] or ["- None recorded."])
    L += ["", "## Evidence gaps"] + [f"- {g.get('label', g.get('item'))}: {g.get('status')} — {g.get('action', g.get('impact', ''))}"
                                     for g in c.missing_evidence]
    L += ["", "## Legal mapping", f"Rules table version {RULES_TABLE_VERSION}; confirmed by: "
          f"{(c.legal or {}).get('confirmed_by') or 'not yet confirmed'}."]
    for r in (c.legal or {}).get("results", []):
        L.append(f"- RULE-{r['key']} — {r['label']}: {'applicable' if r['applicable'] else r['reason']}")
    t, rk = c.triage or {}, c.risk or {}
    L += ["", "---", "## ANNEX — INTERNAL TRIAGE (not evidence; excluded from the brief and the certificate)", "",
          f"- Deterministic risk index: **{rk.get('risk_score')}/100 ({rk.get('band')})** — {rk.get('interpretation')}",
          f"- Method: {rk.get('method')}",
          f"- Bob likelihood band: **{t.get('likelihood_band')}**; probability estimate: "
          f"**{t.get('probability_manipulated')}** ({t.get('probability_label')}, provider {t.get('provider')}, "
          f"estimate confidence {t.get('estimate_confidence')})",
          "- This estimate is not calibrated on any reference population and must not be quoted as a probability "
          "of manipulation in any court-facing document."]
    for x in t.get("reasoning", []): L.append(f"  - {x}")
    L += ["", "## Ledger", f"- Valid: {ledger.get('valid')}; entries: {ledger.get('entries')}; head: `{ledger.get('head')}`"]
    return "\n".join(L)
