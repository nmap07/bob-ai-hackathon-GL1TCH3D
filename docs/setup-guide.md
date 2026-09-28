# Setup Guide

Written for someone who has never seen this repo. Everything runs from the `src/` directory.
Verified on Linux (Ubuntu 24, Python 3.12.3, ffmpeg 6.x): dependencies install, the app runs, all 7 agents complete on a test video and a test image,
reports generate, the MCP server lists 13 tools over STDIO, and `pytest` passes (37 tests). Docker and Windows steps were not re-run.

## 1. Prerequisites
| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 or newer | 3.11 (Dockerfile) and 3.12 (verified) |
| ffmpeg + ffprobe | any recent | Must be on `PATH`. Check: `ffprobe -version` |
| pip | recent | `python -m pip install --upgrade pip` |
| Git | any | To clone your repo |
| IBM Bob IDE | current | Only for the Bob/MCP path (section 6) |
| Docker (optional) | 24+ | Only for section 7 |
| ExifTool (optional) | any | Adds detailed EXIF/XMP/IPTC extraction; otherwise a warning is recorded |
| `c2patool` (optional) | any | Enables real C2PA validation; otherwise a marker-screen fallback runs |
| AASIST ONNX model (optional) | - | `python scripts/fetch_aasist.py` (needs internet to huggingface.co) |

Install ffmpeg: Ubuntu `sudo apt install ffmpeg libsndfile1`; macOS `brew install ffmpeg`; Windows `winget install Gyan.FFmpeg`.

## 2. Environment variables
See `src/.env.example`. **The app does not auto-load `.env`** (no python-dotenv); export variables in your shell, or use docker-compose, which reads `.env`.
The defaults work with no configuration.

| Variable | Default | Purpose |
|---|---|---|
| `BOB_MODE` | `mock` | `mock` = deterministic offline reasoning fallback; `http` = POST to a Bob gateway |
| `BOB_BASE_URL` | empty | Bob gateway URL (only when `BOB_MODE=http`) |
| `BOB_API_KEY` | empty | Bearer token for the gateway (never commit) |
| `BOB_MODEL` | empty | Model name sent in the request body |
| `AASIST_MODEL` | `models/audio/aasist.onnx` | Optional AASIST model path |

## 3. Install
Linux / macOS:
```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/bob-ai-hackathon-YOUR_TEAM_NAME.git
cd bob-ai-hackathon-YOUR_TEAM_NAME/src
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```
Windows PowerShell:
```powershell
cd bob-ai-hackathon-YOUR_TEAM_NAME\src
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```
`requirements.txt` pins `opencv-python>=4.10,<5` on purpose: OpenCV 5.x has no `cv2.CascadeClassifier`, so face detection would be skipped (with a warning). It also lists `Pillow`, needed for image metadata and decoding.

## 4. Run the GUI
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000, click **Upload evidence**, pick a video/image/audio file, click **Start investigation**.

### Make a test clip (no real evidence needed)
```bash
bash ../demo/make_demo_clip.sh          # creates demo/demo_clip.mp4 (synthetic 6 s video + tone)
```
Windows: `ffmpeg -f lavfi -i testsrc=duration=6:size=640x360:rate=25 -f lavfi -i sine=frequency=440:duration=6 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest demo_clip.mp4`

## 5. Verify it works
1. Health: `curl http://127.0.0.1:8000/api/health` -> `{"ok":true,"service":"emafg","bob_mode":"mock"}`
2. Upload the test clip in the GUI. Expected: SHA-256 shown; agent grid shows 7 agents finished (`audio-forensics` and `c2pa-provenance` show warnings that AASIST / c2patool are not installed — this is expected); about 20 observations for a video (about 9 for an image); 5 hypotheses; status `awaiting_review`.
3. Click **Generate report**, then open the *Markdown report* and *JSON package* links. Compare with `demo/sample-output/`.
4. Command-line equivalent: `python run.py ../demo/demo_clip.mp4 --description "controlled demonstration"`
5. Tests: `python -m pytest -q` -> `37 passed`. (Install pytest first if needed: `python -m pip install pytest`.)
6. CLI options: `python run.py FILE --description "..." --case-id MY-CASE-ID` lets you choose the case id.
7. Audit chain: `curl -s http://127.0.0.1:8000/api/cases/CASE-ID` then use the MCP tool `verify_audit_ledger` (section 6), which returns `"valid": true`.

Case data is written to `src/cases/` (git-ignored).

## 6. IBM Bob (MCP) setup
1. Complete section 3 (the `.venv` must exist inside `src/`).
2. In Bob IDE, **open the `src/` folder as the workspace** (Bob reads `src/.bob/mcp.json`).
3. Linux/macOS: replace `.bob/mcp.json` with `.bob/mcp.unix.example.json` (it points to `.venv/bin/python`). Windows uses the shipped file (`.venv/Scripts/python.exe`).
4. Bob settings -> enable **Use MCP Servers** -> confirm `emafg-forensics` is connected (restart Bob if it is not discovered).
5. Run the GUI once to create a case (the MCP layer inspects/reviews/reports on cases; new evidence is ingested via GUI or `run.py`).
6. Ask Bob: *"List the EMAFIG cases and show their status."*, then *"Verify the audit ledger for CASE-..."*. More prompts: `src/docs/BOB_MCP_WINDOWS.md`.
7. Skills: Bob loads project skills from `src/.bob/skills/` (e.g. `judge-demo`, `emafig-bob-orchestrator`).

Headless check of the MCP server (no Bob needed):
```bash
python - <<'PY'
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    p = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env={"PYTHONPATH": "."})
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
asyncio.run(main())
PY
```
Expected: a list of 13 tool names.

Optional HTTP reasoning gateway: `export BOB_MODE=http BOB_BASE_URL=... BOB_API_KEY=... BOB_MODEL=...` (contract is configurable; untested against a live gateway).

## 7. Docker (optional, not built during verification)
```bash
cd src
docker compose up --build        # serves http://localhost:8000; mounts ./cases and ./models
```

## 8. Troubleshooting
| Symptom | Cause | Fix |
|---|---|---|
| `visual-forensics` warning "Haar cascade XML not found ... Face detection skipped" | OpenCV 5.x installed (no face detector) | `pip install "opencv-python>=4.10,<5"` (pinned in requirements.txt) |
| Image metadata warns "Pillow not installed" | Dependency missing | `pip install -r requirements.txt` (Pillow is listed) |
| Agents fail / `metadata-analysis` empty, error 127 | `ffprobe` not on PATH | Install ffmpeg, restart the terminal, check `ffprobe -version` |
| `ModuleNotFoundError: app` / `mcp` | Wrong directory or venv not active | `cd src`, activate `.venv`, re-run `pip install -r requirements.txt` |
| `ImportError: cannot import name 'MCPServer'` | Old `mcp` 1.x installed | `pip install "mcp[cli]>=2.0,<3"` |
| Bob does not show `emafg-forensics` | Wrong workspace or wrong python path | Open `src/` (not repo root); on Linux/macOS use the unix example config; restart Bob |
| Warning "AASIST model not installed" | Optional model absent | Expected. Run `python scripts/fetch_aasist.py` for the extra audio signal |
| Warning "c2patool unavailable" | Optional tool absent | Expected. Install c2patool for real C2PA validation |
| PowerShell blocks `Activate.ps1` | Execution policy | `Set-ExecutionPolicy -Scope Process RemoteSigned` |
| `Address already in use` | Port 8000 taken | Use `--port 8001` |
| `BOB_MODE=http` results show `status: fallback` | Gateway unreachable / wrong contract | Check URL/key/model; the mock fallback keeps the case usable |
