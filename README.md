# EMAFIG — Evidence-Centric Multi-Agent Forensic Investigation Graph

**IBM Bob AI Hackathon submission** · Track: AI

> Deepfake evidence should be *investigated*, not scored. EMAFIG turns a suspect media file into a
> hash-anchored, reproducible, human-reviewable evidence package, and lets IBM Bob operate the investigation.

## Team

| Role | Name | Email |
|---|---|---|
| Team name | GL1TCH3D | |
| Track | AI | |
| Lead | ATHARVA SINGH | princesingh.3045@gmail.com |
| Member | JANYA PARIKH | janyaparikh@gmail.com |
| Member | MAHARSHI PATEL |maharshipatel75139@gmail.com |
| Member | ATHARVA PALLIVAL | paliwal.atharv08@gmail.com |

## Problem Statement

Investigators and courts increasingly receive suspected deepfake video, image and audio as evidence. Most tools collapse
that into one opaque "X% fake" score, which is not reproducible, hides benign explanations (re-encoding, resizing, platform
transcoding) and cannot show how a conclusion was reached. Investigators, forensic examiners and courts need an
auditable chain from the original file to every statement in a report. See `docs/problem-statement.md`.

## Solution

EMAFIG preserves the original file (SHA-256 + SHA-512), runs seven deterministic forensic agents in parallel, and converts
their output into structured **observations** that each list alternative explanations and limitations. Observations feed
competing hypotheses (including "authentic with benign post-processing"), explicit contradictions and evidence gaps.
**IBM Bob** operates the case through a local MCP server and 14 project skills; every action lands in a hash-chained audit
ledger, and a human accepts/rejects observations and signs off the report. See `docs/solution-overview.md`.

## Key Features

1. **Immutable intake + audit chain** — original copied once, hashed (SHA-256/512); append-only hash-chain ledger with a verify call.
2. **Seven parallel forensic agents** — metadata (Pillow/EXIF for images, ffprobe for video, optional ExifTool), compression/sharpness,
   visual (images and up to 32 sampled video frames: face detection, face-boundary, frequency, block-artifact and sharpness screens),
   audio (spectral screen + optional AASIST ONNX), temporal (packet PTS cadence), A/V sync (stream offset), C2PA provenance.
3. **Competing hypotheses, contradictions, evidence gaps** — failures and missing tools are recorded as findings, never hidden.
4. **IBM Bob integration** — STDIO MCP server with 13 tools plus 14 Bob skills describing the staged workflow and guard-rails.
5. **Human-in-the-loop reporting** — per-observation accept/reject, human sign-off, JSON evidence package + Markdown report.

## Tech Stack

- **Languages/frameworks:** Python 3.11+, FastAPI, Uvicorn, Pydantic, SQLite, vanilla JS single-page GUI
- **Forensics:** ffprobe/ffmpeg, OpenCV 4.x, Pillow, librosa, NumPy, optional ONNX Runtime (AASIST), optional ExifTool and `c2patool`
- **IBM technology:** IBM Bob IDE (project-scope MCP config `.bob/mcp.json`, Bob skills in `.bob/skills/`),
  Model Context Protocol (`mcp` Python SDK, STDIO transport), optional Bob HTTP reasoning gateway (`app/bob.py`)
- **Packaging:** Docker / docker-compose, pytest

## How to Run

Exact, tested steps are in `docs/setup-guide.md`. Short version (Linux/macOS; Windows PowerShell equivalents are in the guide):

```bash
cd src
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt      # also needs ffmpeg + ffprobe on PATH
uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000  -> upload a video/image/audio file -> Start investigation
```

Run the tests: `cd src && python -m pip install pytest && python -m pytest -q` (37 tests)

## Demo

- Demo video: see `demo/demo-video-link.txt`
- Live demo: see `demo/live-demo-url.txt` (`NOT DEPLOYED` — runs locally)
- Screenshots: `demo/screenshots/`
- Real sample output from a run (report, JSON package, audit ledger): `demo/sample-output/`
- Slides: `presentation/slides.pptx`

## Known Limitations

We would rather be accurate than impressive:

- **Detectors are screening heuristics, not a validated deepfake classifier.** Face detection is Haar-based; audio uses a
  spectral-flux 3-sigma screen; temporal/A-V checks read container timing. Nothing is calibrated to a probability, and the
  app never outputs a "real/fake" verdict. Heuristics can fire on clean media (a clean synthetic test clip trips the audio
  spectral screen).
- **The in-app Bob HTTP path defaults to `BOB_MODE=mock`** (deterministic offline fallback with five fixed hypothesis
  templates). The real Bob path is the MCP server + skills. We have not tested the HTTP gateway against a live Bob endpoint,
  and the MCP server was verified with a generic MCP STDIO client rather than inside every Bob IDE version.
- Skeptic / adversarial / legal-proposer outputs are stored in the case state but are not yet rendered in the GUI or report.
- `app/forensics/deepfake_model.py` (optional ONNX/PyTorch detector adapter) is included but not yet called by any agent; the visual agent reports
  `ML model: unavailable`. No trained visual deepfake model is bundled.
- `core/plane_c/` (ACH matrix, legal rules engine, custody log, BSA s.63 certificate data pack) ships in the repo but is not
  yet called by `app/`. The BSA certificate is never completed or signed by software.
- `.bob/custom_modes.yaml` and `.bob/rules/EMAFIG.md` are empty; the workflow lives in the skills. The MCP tool
  `start_investigation` is a status stub — new evidence is ingested through the GUI or `run.py`.
- AASIST audio model is optional and not bundled (download via `scripts/fetch_aasist.py`); C2PA verification needs `c2patool`
  (otherwise only a byte-marker screen runs and a warning is recorded).
- `.env` is not auto-loaded (no python-dotenv): export variables in your shell, or use docker-compose.
- The API has no authentication — local/demo use only. Docker files were not built during verification.
- Verified on Linux with Python 3.12; Windows steps follow the project docs but were not re-run by us.
- Hackathon/research prototype, not a certified forensic product; it cannot guarantee admissibility.

## What We're Most Proud Of

- The **evidence-centric contract**: every statement traces original SHA-256 -> observation -> agent -> artifact hash, and
  failed or missing channels are surfaced as evidence gaps instead of being swallowed.
- **Honest uncertainty by design**: each observation carries alternative explanations and limitations; correlated detectors
  are not counted as independent proof; C2PA absence is a gap, not an accusation.
- **Bob as a bounded operator**: 13 narrowly-scoped MCP tools (no shell, no delete, no write access to originals) and skills
  that forbid invented measurements, invented legal sections and model-score-only verdicts.
