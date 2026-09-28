---
name: metadata-analysis
description: Extract and cross-check container, stream, EXIF/XMP/IPTC, filesystem, and encoder metadata.
user-invocable: true
---

# metadata-analysis

> **Court-readiness qualification:** No software can guarantee admissibility or make an evidence package “foolproof.” The objective is reproducibility, integrity, auditability, and a complete trace for human investigators, forensic experts, and counsel. India’s Bharatiya Sakshya Adhiniyam, 2023 contains electronic-record provisions and a certificate schedule under section 63(4)(c), including hash and source/device details; the responsible human must complete any applicable statutory certificate, and an AI agent must never fabricate or sign one.


## Plane B integration

**Plane B role (from diagram):** `examiner-metadata` — runs after intake; operates on the same immutable source.

**Receives from orchestrator:**
- `case_id`, `evidence_id`, immutable source URI
- Canonical source hash from `forensic-intake` (mandatory — re-verify before first byte read)
- Stream inventory from `forensic-intake` (optional accelerator; do not trust without re-hashing)
- Environment-identity token, operator run ticket

**Emits to orchestrator (exchange layer only):**
- `EMAFIG-FR-1.0` envelope with `agent_id: "metadata-analysis"`
- Normalized + raw metadata fields: container, stream, EXIF/XMP/IPTC, GPS, encoder, dates/timezones
- Cross-check table: fields where ExifTool ↔ MediaInfo ↔ FFprobe agree or disagree
- List of anomalies with benign alternative explanations included

**Feeds into:**
| Skill | What it supplies |
|---|---|
| `temporal-analysis` | Reported FPS, time-base, timecode, encoder/muxer info |
| `hypothesis-analysis` | Metadata anomaly observations + benign explanations |
| `evidence-graph` | Validated metadata observation nodes |
| `forensic-reporting` | Raw + normalized metadata, cross-check table |

**Upstream requirement:** `forensic-intake` must have status `completed` or `completed_with_warnings` before this skill runs.

## Mission
Extract and cross-check container, stream, EXIF/XMP/IPTC, filesystem, and encoder metadata.

## Strict isolation boundary
This is a single-purpose forensic worker. It MUST operate independently of every other skill/agent. It may read only the immutable evidence package, explicit control/reference inputs, and its own configuration. It writes only to its private run directory. It MUST NOT call another agent/skill/subagent or read another agent’s private workspace. Cross-agent exchange occurs only through the orchestrator/evidence-exchange layer. Network access is denied by default.

## Approved tools
ExifTool, MediaInfo, FFprobe, Python, Pydantic, jsonschema

## Installation

```bash
sudo apt-get update && sudo apt-get install -y libimage-exiftool-perl ffmpeg mediainfo python3-venv
python3 -m venv .venv && source .venv/bin/activate
python -m pip install pydantic jsonschema orjson
```
Windows: install the three binaries from official releases and record exact versions.

## Inputs
Required: `case_id`, `evidence_id`, immutable source reference, source hash, acquisition/custody manifest, controlled execution-environment identifier. Optional inputs must be explicitly supplied and hashed.

## Workflow
1. Hash the exact input before parsing.
2. Extract metadata independently with ExifTool, MediaInfo, and FFprobe where applicable.
3. Preserve complete raw outputs.
4. Normalize only derived fields; retain original names and values.
5. Cross-check dates, timezones, duration, FPS, codecs, encoder tags, GPS, color profiles, streams, chapters, attachments, and warnings.
6. Document benign explanations such as re-encoding, export, platform processing, or metadata stripping.


## Required metadata preservation
When present, preserve raw values for size, MIME, container, duration, stream count, codecs/profiles/levels, pixel/sample format, resolution, FPS/time-base, timecode, encoder/software, dates/timezones, EXIF/XMP/IPTC, GPS, color profiles, chapters, attachments, side data, and parser warnings.

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
- Never modify metadata.
- Never treat missing metadata as proof of manipulation.
- Never collapse conflicting timestamps without preserving all raw values and timezone assumptions.


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
