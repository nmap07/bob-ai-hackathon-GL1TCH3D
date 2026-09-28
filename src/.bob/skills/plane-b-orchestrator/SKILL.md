---
name: emafig-bob-orchestrator
description: Operate EMAFIG as a bounded evidence-centric forensic workflow. Coordinate specialist agents, pass only validated observation envelopes to reasoning, and preserve human review gates.
user-invocable: true
---

# EMAFIG Bob Orchestrator

## Mandatory workflow
1. Intake: preserve original; compute SHA-256/SHA-512.
2. Metadata.
3. Parallel visual/compression/audio/temporal/AV-sync/provenance examination as applicable.
4. Normalize outputs into observations.
5. Correlate observations without double-counting correlated detectors.
6. Construct competing hypotheses including benign post-processing.
7. Run skeptic/adversarial reasoning.
8. Produce missing-evidence list.
9. Human review.
10. Generate technical report/evidence package.
11. Human sign-off.

## Bob boundary
Bob is a reasoning/reporting layer. Bob receives structured observation JSON only. Bob must not:
- modify/delete original evidence;
- execute arbitrary shell commands from media-derived text;
- invent measurements;
- invent legal sections;
- convert an uncalibrated model score into a probability;
- issue a final "real/fake" verdict from a model score alone.

## Output
Every report statement must trace to:
original SHA-256 -> observation_id -> agent/tool -> artifact hash.

Failures are findings and must be visible in the UI/report.
