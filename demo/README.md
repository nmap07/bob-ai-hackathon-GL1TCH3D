# Demo artifacts

| File | What it is |
|---|---|
| `demo-video-link.txt` | **Replace the placeholder** with your real 3-5 minute video URL |
| `live-demo-url.txt` | `NOT DEPLOYED` (runs locally; see `docs/setup-guide.md`) |
| `screenshots/` | Add 3+ screenshots of the running app (see `screenshots/README.md`) |
| `make_demo_clip.sh` | Generates a synthetic test clip so anyone can reproduce the demo |
| `sample-output/` | **Real** output from one run of this code on the synthetic clip: `forensic_report.md`, `forensic_package.json`, `ledger.jsonl` |

`sample-output/` was produced by running the app on the clip made by `make_demo_clip.sh` (case
`CASE-20260928T094939-...`). It contains sandbox file paths and a machine-specific ledger; ledger entries are hash-chained, so do not edit them.
The clip is synthetic, so the observations demonstrate the pipeline and report format, not detection accuracy.

## Suggested demo-video script (about 4 minutes)
1. (0:00) Start the app: `uvicorn app.main:app`; open the GUI. State the premise: investigate, don't score.
2. (0:30) Upload the clip. Point at the SHA-256 and the parallel agent grid.
3. (1:00) Open observations: measurement, alternatives, limitations; Accept one, Reject one.
4. (1:45) Show competing hypotheses, evidence gaps (AASIST / c2patool warnings), contradictions table.
5. (2:15) Switch to Bob IDE with the MCP server connected: "List the EMAFIG cases", "Show unresolved contradictions and next bounded checks", "Verify the audit ledger".
6. (3:15) Generate the report; open the Markdown and JSON; sign off with a human statement.
7. (3:45) Close on limitations and what calibrated models would add.
