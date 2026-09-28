---
name: judge-demo
description: Run the EMAFIG judge demonstration and expose traceability rather than a black-box fake/real score.
user-invocable: true
---

# Judge Demo

Use one controlled evidence file.

Demo order:
1. Upload.
2. Show SHA-256.
3. Show immutable original.
4. Show parallel agent execution.
5. Open visual/audio/temporal/metadata observations.
6. Show AASIST raw signal if configured.
7. Show competing hypotheses.
8. Show contradiction table.
9. Show evidence gaps.
10. Show "why did this finding happen?" trace.
11. Generate JSON + Markdown report.
12. Human sign-off.

Judge-facing differentiator:
The product does not hide contradictions or let five correlated detectors become "five independent proofs."
