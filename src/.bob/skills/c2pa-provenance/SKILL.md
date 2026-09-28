---
name: c2pa-provenance
description: Inspect C2PA Content Credentials and provenance manifests without mutating the source.
user-invocable: true
---

# c2pa-provenance

> **Court-readiness qualification:** No software can guarantee admissibility or make an evidence package “foolproof.” The objective is reproducibility, integrity, auditability, and a complete trace for human investigators, forensic experts, and counsel. India’s Bharatiya Sakshya Adhiniyam, 2023 contains electronic-record provisions and a certificate schedule under section 63(4)(c), including hash and source/device details; the responsible human must complete any applicable statutory certificate, and an AI agent must never fabricate or sign one.


## Plane B integration

**Plane B role (from diagram):** `examiner-metadata` (provenance sub-track) — runs in parallel with the examiner wave; depends only on `forensic-intake`.

**Receives from orchestrator:**
- `case_id`, `evidence_id`, immutable source URI
- Canonical source hash from `forensic-intake` (mandatory re-verify)
- Environment-identity token, operator run ticket

**Emits to orchestrator (exchange layer only):**
- `EMAFIG-FR-1.0` envelope with `agent_id: "c2pa-provenance"`
- Full raw C2PA report/manifest JSON (preserved exactly)
- Parsed credential fields: manifest IDs, assertions, ingredients, actions, timestamps, signer info, certificate chain
- Signature verification status for each manifest
- Discrepancies between C2PA claims and container/stream observations, with benign explanations
- Absence of C2PA explicitly recorded as `not_applicable`, not as an anomaly

**Feeds into:**
| Skill | What it supplies |
|---|---|
| `hypothesis-analysis` | Provenance credential status + discrepancy observations |
| `evidence-graph` | Provenance nodes linked to source artifact node |
| `forensic-reporting` | C2PA manifest report, verification status |

**Upstream requirement:** `forensic-intake` must have status `completed` or `completed_with_warnings`.

## Mission
Inspect C2PA Content Credentials and provenance manifests without mutating the source.

## Strict isolation boundary
This is a single-purpose forensic worker. It MUST operate independently of every other skill/agent. It may read only the immutable evidence package, explicit control/reference inputs, and its own configuration. It writes only to its private run directory. It MUST NOT call another agent/skill/subagent or read another agent’s private workspace. Cross-agent exchange occurs only through the orchestrator/evidence-exchange layer. Network access is denied by default.

## Approved tools
c2patool, c2pa-python, Python, SHA-256/SHA-512

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install c2pa-python pydantic jsonschema orjson
c2patool -V
c2patool -h
```
Install the `c2patool` prebuilt binary for the operating system from the official release and put it on PATH.

## Inputs
Required: `case_id`, `evidence_id`, immutable source reference, source hash, acquisition/custody manifest, controlled execution-environment identifier. Optional inputs must be explicitly supplied and hashed.

## Workflow
1. Hash the source before provenance inspection.
2. Preserve complete C2PA reports/manifests.
3. Verify signatures where supported and record verification/certificate information.
4. Record manifest identifiers, assertions, ingredients, actions, timestamps, signer information exposed by the manifest, and warnings/errors.
5. Compare provenance claims to container/stream observations without treating disagreement as proof of tampering.


## Provenance trust model
C2PA establishes provenance/credential information, not factual truth. Preserve verification status and all manifest relationships/errors.

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
- Never add, rewrite, strip, or sign a manifest on original evidence.
- Never treat presence of C2PA as proof that all content is truthful.
- Never treat absence of C2PA as proof of manipulation.


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
