---
name: forensic-reporting
description: Compile immutable forensic outputs into a traceable investigation report with annexures and audit trail.
user-invocable: true
---

# forensic-reporting

> **Court-readiness qualification:** No software can guarantee admissibility or make an evidence package “foolproof.” The objective is reproducibility, integrity, auditability, and a complete trace for human investigators, forensic experts, and counsel. India’s Bharatiya Sakshya Adhiniyam, 2023 contains electronic-record provisions and a certificate schedule under section 63(4)(c), including hash and source/device details; the responsible human must complete any applicable statutory certificate, and an AI agent must never fabricate or sign one.


## Plane B integration

**Plane B role (from diagram):** `drafter-brief` / `drafter-victim` — terminal skill; runs only after the full pipeline is complete and all envelopes are committed to the evidence graph.

**Receives from orchestrator:**
- `case_id`, `evidence_id`
- Hash-verified `EMAFIG-FR-1.0` envelopes from **all** upstream skills (every stage)
- Deterministic graph snapshot + hash from `evidence-graph`
- Pipeline completion manifest: status of every skill run (completed / warnings / failed / not_run)
- Operator-supplied case metadata: case title, exhibit list, report classification, recipient
- Environment-identity token, operator run ticket
- **No direct source-media access; reads only from the validated exchange layer**

**Emits to orchestrator (exchange layer only):**
- `EMAFIG-FR-1.0` envelope with `agent_id: "forensic-reporting"`
- `report.pdf` + `report.json` (deterministic, byte-for-byte reproducible given same inputs)
- `evidence-index.json`, `custody-log.json`, `tool-manifest.json`
- `observations/`, `raw-tool-output/`, `derived-artifacts/`, `model-manifests/`, `hashes/`
- `certificates/` — draft data pack only; statutory certificate (BSA 2023 s.63(4)(c)) left blank for authorized human to complete and sign
- `validation/` — completeness audit results

**Upstream requirements:** **All** pipeline skills must have recorded a terminal status (`completed`, `completed_with_warnings`, `failed`, or `not_applicable`). A missing terminal status is a blocking error — the report must not be finalized.

## Mission
Compile immutable forensic outputs into a traceable investigation report with annexures and audit trail.

## Strict isolation boundary
This is a single-purpose forensic worker. It MUST operate independently of every other skill/agent. It may read only the immutable evidence package, explicit control/reference inputs, and its own configuration. It writes only to its private run directory. It MUST NOT call another agent/skill/subagent or read another agent’s private workspace. Cross-agent exchange occurs only through the orchestrator/evidence-exchange layer. Network access is denied by default.

## Approved tools
Python, Jinja2, WeasyPrint, PyMuPDF, Pydantic, jsonschema, SHA-256/SHA-512, optional qpdf

## Installation

```bash
sudo apt-get update && sudo apt-get install -y python3-venv qpdf
python3 -m venv .venv && source .venv/bin/activate
python -m pip install jinja2 weasyprint pymupdf pydantic jsonschema orjson
```

## Inputs
Required: `case_id`, `evidence_id`, immutable source reference, source hash, acquisition/custody manifest, controlled execution-environment identifier. Optional inputs must be explicitly supplied and hashed.

## Workflow
1. Accept only hash-verified forensic envelopes and referenced artifacts.
2. Validate every envelope before compilation.
3. Map every factual statement to evidence_id, artifact hash, observation_id, and tool-run ID.
4. Separate evidence handling, methods, raw observations, measurements, interpretations, hypotheses, adversarial checks, limitations, and legal/procedural notes.
5. Include negative findings, failures, missing data, and unresolved contradictions.
6. Preserve raw outputs, model hashes, tool manifests, and execution environments.
7. Generate deterministic report + machine-readable package; hash every report/annexure.
8. Generate only a draft data pack for any statutory certificate and leave legal completion/signing to authorized humans.
9. Run a final completeness audit before release.


## Recommended report package
```text
case-report/
  report.pdf
  report.json
  evidence-index.json
  custody-log.json
  tool-manifest.json
  observations/
  raw-tool-output/
  derived-artifacts/
  model-manifests/
  hashes/
  certificates/
  validation/
```
The PDF is the presentation layer. Preserve machine-readable JSON, raw tool output, hashes, and provenance as the technical record.

## Mandatory controls
- Verify source integrity before and after analysis.
- Preserve original bytes and raw tool output.
- Record exact versions, commands, exit codes, warnings, parameters, model hashes, and environment identity.
- Hash every derived artifact.
- Record positive, negative, failed, skipped, and unavailable tests.
- Use deterministic settings where supported.
- Version-control code/config/model/schema/prompt inputs that materially affect results.
- Maintain trace: report statement -> observation_id -> tool_run_id -> derived artifact hash -> original evidence hash.

## Failure handling
A failure is itself a recorded result. Preserve stderr/error text, tool version, exact invocation, source-integrity status, and required follow-up. Never silently skip a failed test and never overwrite a prior failed run.

## Prohibited behavior
- Never invent legal sections, facts, dates, identities, or conclusions.
- Never remove inconvenient findings.
- Never edit raw outputs.
- Never present an automated score as definitive authenticity proof.


## Mandatory forensic JSON contract

Every run MUST emit one machine-readable JSON envelope using schema version `EMAFIG-FR-1.0`. No ad-hoc output is permitted.

```json
{
  "schema_version": "EMAFIG-FR-1.0",
  "run": {"run_id":"uuid","agent_id":"skill-name","agent_version":"semver-or-git-sha","started_utc":"ISO-8601","ended_utc":"ISO-8601","status":"completed|completed_with_warnings|failed|not_applicable","operator_id":"controlled-id","host_id":"controlled-id","environment_id":"container-image-digest-or-equivalent"},
  "case": {"case_id":"id","evidence_id":"id","exhibit_id":"id-or-null","source_uri":"controlled-reference"},
  "inputs": {"artifacts":[{"artifact_id":"uuid","filename":"original","size_bytes":0,"mime_type":"detected","sha256":"hex","sha512":"hex","source_hash_verified":true,"access_mode":"read_only"}]},
  "tools_used": [{"name":"tool","version":"exact","path_or_image":"path-or-image","vendor":"vendor","command":"exact-command-secrets-redacted","exit_code":0,"stdout_sha256":"hex-or-null","stderr_sha256":"hex-or-null"}],
  "result": {"result_type":"observation|measurement|verification|correlation|failure","summary":"strictly factual","observations":[{"observation_id":"uuid","category":"controlled-term","statement":"what was observed","location":"frame/time/range/etc","measurement":{},"basis":["artifact-id","tool-run-id"],"supports":[],"contradicts":[],"alternative_explanations":[],"confidence":{"value":0.0,"method":"validated-method","meaning":"defined meaning"}}],"limitations":[],"not_tested":[],"required_follow_up":[]},
  "output": {"artifacts":[{"artifact_id":"uuid","type":"json|csv|image|audio|video|log|report|other","path":"controlled-output-reference","size_bytes":0,"sha256":"hex","sha512":"hex"}]},
  "provenance": {"parent_artifact_hashes":[],"derived_from_observation_ids":[],"processing_steps":[],"transformations":[]},
  "validation": {"checks":[{"check":"name","status":"passed|failed|not_run","details":"details"}],"repeatability_status":"tested|not_tested|failed","independent_review_required":true},
  "chain_of_custody": {"event_ids":[],"source_preservation_verified":true,"write_protection_verified":true},
  "security": {"network_access":false,"source_modified":false,"temporary_files_outside_sandbox":false},
  "errors":[],
  "signature": {"status":"unsigned|signed|signature_failed","algorithm":"controlled-value-or-null","key_id":"controlled-id-or-null","value":"signature-or-null"}
}
```

### Output rules
1. Claims must be traceable to an input artifact and tool run.
2. Hash every input and every derived artifact with SHA-256 and SHA-512 where available.
3. Record exact tool versions, commands, exit codes, warnings, and environment identity.
4. Record failures, timeouts, unsupported formats, skipped tests, and missing inputs.
5. Preserve raw tool output exactly.
6. Use UTC internally.
7. Never overwrite a prior run; every rerun gets a new `run_id`.
8. The original evidence is immutable/read-only.
9. No agent reads another agent’s private workspace. Cross-agent exchange occurs only through the orchestrator/evidence-exchange layer using validated result envelopes.
10. Never invent missing values. Use `null`, `[]`, or an explicit not-available/not-tested state.
11. Separate observation, measurement, interpretation, hypothesis, and legal analysis.
12. Do not emit a final binary “real/fake” conclusion from an automated score alone.

## Isolation contract
- Read-only mount: immutable evidence + explicit input manifest.
- Write-only private output directory for this run.
- No shared mutable filesystem.
- No direct agent-to-agent calls.
- Network disabled by default.
- Explicit binary/library allow-list.
- CPU/RAM/process/wall-clock quotas.
- Record container/image digest or equivalent environment fingerprint.
- Model files, reference datasets, prompts, and configuration are versioned and hashed.


## Validation checklist
- [ ] Input hash verified.
- [ ] Source unmodified.
- [ ] Exact tool versions captured.
- [ ] Exact commands captured.
- [ ] Raw outputs preserved.
- [ ] Derived outputs hashed.
- [ ] Every observation has a precise location and basis.
- [ ] Limitations and not-tested items recorded.
- [ ] No private cross-agent access occurred.
- [ ] JSON conforms to `EMAFIG-FR-1.0`.
- [ ] Independent review marked required for material findings.

## Definition of done
A third party must be able to reconstruct what was examined, the exact bytes, tools and versions, commands and parameters, observations and locations, derived artifacts and hashes, limitations, and unresolved questions without relying on hidden agent state.
