# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project identity

EMAFIG — a court-readiness forensic analysis system for digital media evidence. All skills are Plane B reasoning workers (Bob Shell modes: JSON in, JSON out, no tools except approved binaries). Every run emits an `EMAFIG-FR-1.0` JSON envelope. Schema version and output contract are defined in [`EMAFIG-FORensic-Output-Contract.md`](EMAFIG-FORensic-Output-Contract.md).

---

## Plane B skill map

```
ORCHESTRATOR (plane-b-orchestrator)
│
│  STAGE 0 — blocking gate
├─► forensic-intake          examiner-metadata / first worker
│        │ canonical source hash ──────────────────────────────┐
│        │                                                      │ (all skills re-verify)
│  STAGE 1 — parallel wave                                     │
├─► metadata-analysis        examiner-metadata                  │
├─► visual-forensics         examiner-visual                    │
├─► audio-forensics          examiner-audio                     │
├─► temporal-analysis        examiner-compression               │
├─► c2pa-provenance          examiner-metadata (provenance)     │
│        │ all envelopes validated                              │
│  STAGE 1.5 — evidence-graph (ingestion batch 1)              │
│        │                                                      │
│  STAGE 2 — needs visual + audio + temporal done              │
├─► av-sync-analysis         examiner-audio (cross-modal)  ◄───┘
│        │
│  STAGE 2.5 — evidence-graph (ingestion batch 2)
│        │
│  STAGE 3 — reasoning only, no source access
├─► hypothesis-analysis      hypothesis-assessor
│        │
│  STAGE 3.5 — evidence-graph (ingestion batch 3)
│        │
│  STAGE 4 — adversarial challenge
├─► adversarial-verification skeptic + verifier
│        │
│  STAGE 4.5 — evidence-graph (ingestion batch 4, final snapshot)
│        │
│  STAGE 5 — terminal; requires complete pipeline manifest
└─► forensic-reporting       drafter-brief / drafter-victim
```

### Skill → Plane B role mapping

| Skill | Plane B role | Stage |
|---|---|---|
| `forensic-intake` | examiner-metadata | 0 |
| `metadata-analysis` | examiner-metadata | 1 |
| `visual-forensics` | examiner-visual | 1 |
| `audio-forensics` | examiner-audio | 1 |
| `temporal-analysis` | examiner-compression | 1 |
| `c2pa-provenance` | examiner-metadata (provenance) | 1 |
| `av-sync-analysis` | examiner-audio (cross-modal) | 2 |
| `hypothesis-analysis` | hypothesis-assessor | 3 |
| `adversarial-verification` | skeptic + verifier | 4 |
| `evidence-graph` | verifier (graph layer) | 1.5 / 2.5 / 3.5 / 4.5 |
| `forensic-reporting` | drafter-brief / drafter-victim | 5 |
| **`plane-b-orchestrator`** | **coordinator — drives all above** | **all** |

---

## Critical non-obvious rules

1. **No skill ever calls another skill directly.** All cross-skill data passes through the orchestrator's evidence-exchange layer as hash-verified `EMAFIG-FR-1.0` envelopes. A skill that receives data from another skill receives only an envelope hash-reference routed by the orchestrator.

2. **`forensic-intake` is the only source of the canonical source hash.** Every other skill must re-verify the source hash it receives from the orchestrator against this value before reading one byte. Hash mismatch → immediate `failed` status, no retry, escalate to operator.

3. **`hypothesis-analysis` has zero direct source-media access.** It works only from observation envelopes. Giving it the source URI is a contract violation.

4. **`evidence-graph` is append-only.** Corrections to observations create new nodes with `SUPERSEDES` edges. Destructive in-place updates are forbidden.

5. **`forensic-reporting` cannot start unless every pipeline skill has a terminal status** — including `failed` and `not_applicable`. A missing status is a hard blocking error.

6. **The BSA 2023 s.63(4)(c) certificate is never completed or signed by any agent.** `forensic-reporting` emits only a draft data pack; the authorized human completes and signs it.

7. **`hypothesis-analysis` must never emit a guilt/authenticity verdict or binary "real/fake" conclusion.**
   The only probability-like number allowed is the `risk-assessor` triage estimate, labelled
   `llm_estimate_uncalibrated` (or `heuristic_from_risk_index` for the fallback). It is shown to the officer for
   prioritisation only and is excluded from the investigation brief and the BSA 63(4) certificate; the Verifier
   keeps rejecting percentages there. Every observation carries a `baseline` comparison against the built-in,
   uncalibrated profile in `app/baselines.py`; the 0-100 risk index counts each independence group once.

8. **Model counts ≠ evidence counts.** Multiple detectors using identical frames/preprocessing are correlated measurements. `hypothesis-analysis` must model detector dependencies explicitly.

9. **Every rerun gets a new `run_id` and `pipeline_run_id`.** Prior runs are never overwritten.

10. **All orchestrator events are write-once, append-only** in the SQLite run log. The run log SHA-256 is recorded in the orchestrator's own `EMAFIG-FR-1.0` envelope.

---

## Output contract

All skills emit `EMAFIG-FR-1.0` envelopes. Schema defined in [`EMAFIG-FORensic-Output-Contract.md`](EMAFIG-FORensic-Output-Contract.md). Key fields:
- `run.agent_id` — must match the skill name exactly
- `inputs.artifacts[].source_hash_verified` — must be `true` for any skill accessing source media
- `result.observations[].basis` — every observation must cite an `artifact_id` and `tool_run_id`
- `validation.independent_review_required` — always `true` for material findings

---

## Skills location

All skills live in [`.bob/skills/`](.bob/skills/). Each has a [`SKILL.md`](.bob/skills/forensic-intake/SKILL.md) with mission, approved tools, installation, workflow, Plane B integration section, and validation checklist.
