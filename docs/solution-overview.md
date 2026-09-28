# Solution Overview

## Core mechanism
EMAFIG separates **observing**, **reasoning** and **deciding**:

```text
immutable evidence -> specialist forensic agents -> structured observations
   -> competing hypotheses / contradictions / evidence gaps (Bob-assisted)
   -> human review -> forensic report + audit ledger
```

- **Observing (deterministic, no LLM):** seven agents measure the file and emit `Observation` records (id, agent + version, type,
  statement, location, measurement, basis, supports/contradicts, alternative_explanations, limitations, calibrated flag, review status).
- **Reasoning (IBM Bob):** Bob sees structured observations, never the raw file. Through the MCP server it reads observations,
  hypotheses, contradictions and gaps, proposes next bounded checks, verifies the audit ledger, and drives review/report actions.
- **Deciding (human):** the investigator accepts or rejects observations and signs off. Software never signs the BSA s.63 certificate.

## What makes it different from a naive detector
| Naive "deepfake detector" | EMAFIG |
|---|---|
| One score | Many typed observations with measurements |
| No benign explanation | Every observation lists alternatives; H4 "authentic + benign post-processing" is always a hypothesis |
| Failures hidden | Failed / not-applicable / warning states become **evidence gaps** in the report |
| Trust the model | Model outputs (e.g. AASIST) are stored raw and never converted to a probability without a validated operating point |
| No audit | Append-only SHA-256 hash-chain ledger, verifiable by `verify_audit_ledger` |
| LLM decides | LLM/Bob is a bounded reasoning layer with human review and sign-off |

## Key design decisions
1. **Original is copied once and hashed first** (SHA-256 + SHA-512); all analysis uses derivatives in a per-case workspace.
2. **Agents run in parallel** (`asyncio.gather`, blocking work in threads); one agent failing does not stop the others, and the failure is recorded.
3. **Bob via MCP, not a guessed REST API.** Bob IDE documents project-scope `.bob/mcp.json` and local STDIO servers; we expose only read/inspect, review, report and sign-off tools (13 in total, including a focused `get_visual_analysis`). No shell, no delete, no write to originals.
4. **Skills as the contract.** `.bob/skills/*` (14 skills) describe each stage, the approved tools and hard rules (see `src/AGENTS.md`): hypothesis analysis has no source-media access, evidence graph is append-only, reporting cannot start until every agent has a terminal status, no real/fake verdict.
5. **Honest scoring.** `calibrated` is false for heuristics; limitations ship with every observation and again in the report.
6. **Optional model channels.** AASIST (audio anti-spoofing ONNX) and C2PA (`c2patool`) plug in when installed and degrade to explicit warnings when not.

## The user experience
1. **GUI (Forensic Control Room):** upload evidence -> the SHA-256 appears immediately -> an agent grid shows parallel execution and statuses -> each observation shows measurement, alternatives, and Accept / Reject buttons -> hypotheses table, evidence gaps -> Generate report / Human sign-off -> download the Markdown report and JSON package.
2. **Bob IDE:** open `src/` as the workspace, enable MCP, and ask in natural language, for example *"Show every unresolved contradiction in CASE-... and propose the next bounded forensic checks"* or *"Verify the audit ledger for CASE-..."*. Demo prompts are in `src/docs/BOB_MCP_WINDOWS.md`.
3. **CLI:** `python run.py evidence.mp4 --description "..."` prints the full case JSON.

## Honest scope
Detectors are screening heuristics. The value of this submission is the traceable, reviewable investigation workflow around them, with a clear
plug-in point for calibrated models. See "Known Limitations" in `README.md`.
