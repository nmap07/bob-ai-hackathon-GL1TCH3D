# src/ — EMAFIG source code

Everything needed to run EMAFIG lives in this directory. Treat `src/` as the project root:
run all commands from here and open **this folder** as the IBM Bob workspace (Bob reads `.bob/` from the workspace root).

```text
src/
├── app/                    FastAPI app + investigation engine
│   ├── main.py             REST API + serves the GUI
│   ├── engine.py           Orchestrator: intake -> parallel agents -> reasoning -> report
│   ├── bob.py              Bob reasoning boundary (mock / http)
│   ├── schemas.py          Pydantic models: Observation, Hypothesis, CaseState ...
│   ├── store.py            SQLite case store + hash-chained audit ledger
│   ├── agents/             7 deterministic forensic examiners (+ intake)
│   ├── forensics/          tooling.py (tool resolver), deepfake_model.py (optional model adapter, not yet wired in)
│   └── ui/index.html       Single-page "Forensic Control Room" GUI
├── mcp_server.py           IBM Bob <-> EMAFIG MCP server (STDIO, 13 tools)
├── .bob/                   Bob project config: mcp.json (+ unix example) and 14 skills in skills/
├── core/plane_c/           Deterministic trust-services library (ACH, legal rules, custody,
│                           BSA s.63 certificate data pack). Standalone; NOT yet wired into app/
├── run.py                  CLI: analyse one evidence file (--description, --case-id, --signoff)
├── scripts/                fetch_aasist.py (optional model download), test_visual_pipeline.py (manual visual check)
├── tests/                  pytest suite (37 tests: pipeline, visual image/video/failure modes, Windows tool resolution)
├── data/legal_sources.json Versioned list of approved legal sources
├── docs/                   Original design/integration notes (BOB_*.md, PROJECT_README.md)
├── Dockerfile, docker-compose.yml, requirements.txt, .env.example
└── AGENTS.md, EMAFIG-*.md  Skill contract, output contract, court-readiness notes
```

Full run instructions: `../docs/setup-guide.md`.
The original, longer project README is preserved at `docs/PROJECT_README.md`.
