# EMAFIG — Evidence-Centric Multi-Agent Forensic Investigation Graph
## IBM Bob / Deepfake Criminal-Investigation Submission Build

### What this folder is
A runnable, judge-facing implementation of the architecture in the supplied EMAFIG design:
**immutable evidence → specialist forensic agents → structured observations → Bob reasoning → competing hypotheses → contradictions → evidence gaps → human review → forensic report**.

The supplied architecture explicitly separates observation, correlation, hypothesis formation, adversarial verification, human review and reporting, and says the LLM is a reasoning/reporting layer rather than the sole detector. The implementation keeps that boundary.

### Supported inputs
- Images: JPG/JPEG/PNG/WebP/BMP/TIFF/GIF
- Video: MP4/MOV/MKV/AVI/WebM/M4V/3GP/MTS/M2TS
- Audio: WAV/FLAC/MP3/M4A/AAC/OGG/OPUS

### Agents
| Plane | Agent | Function |
|---|---|---|
| C | forensic-intake | Preserve original + SHA-256/SHA-512 |
| C/B | metadata-analysis | FFprobe media/container/stream facts |
| C/B | compression-analysis | deterministic compression/sharpness screening |
| C/B | visual-forensics | frame sampling + face/edge screening |
| C/B | audio-forensics | spectral/noise screening |
| C/B | audio-deepfake-aasist | optional AASIST ONNX raw anti-spoofing signal |
| C/B | temporal-analysis | PTS/cadence/GOP-adjacent packet timing |
| C/B | av-sync-analysis | stream-level audio/video offset |
| C/B | c2pa-provenance | C2PA validation when c2patool is installed |
| B | hypothesis-assessor | competing hypotheses |
| B | skeptic | benign explanations / confirmation-bias checks |
| B | adversarial | "try to disprove it" test plan |
| B | legal-proposer | candidate legal mapping only; no invented sections |
| C | hash ledger | append-only audit chain |
| B/C | report compiler | evidence package + judge-readable report |

### Bob integration
`app/bob.py` is the only application boundary for Bob reasoning.

- `BOB_MODE=mock` makes the demo work offline.
- `BOB_MODE=http` sends JSON to the Bob inference gateway configured by the hackathon environment.
- The exact Bob endpoint contract is intentionally not hard-coded or fabricated. Put the endpoint, key and model in `.env`/the runtime environment supplied by IBM.
- Bob receives structured observations, not raw evidence files.
- Bob cannot modify the original evidence.

This pattern follows public IBM Bob hackathon examples where Bob is used for AI prose/reasoning while deterministic fallback keeps the demo functional when the Bob service is unavailable. See the cited public example in the project documentation.

### Audio deepfake model
The optional AASIST integration is based on the published AASIST architecture and its maintained inference model. AASIST consumes raw speech and produces an anti-spoofing score; the model card reports that higher score means more bona-fide speech. The application preserves the raw model output and **does not turn it into a probability or legal conclusion**.

Download:
```bash
python scripts/fetch_aasist.py
```

Then install `onnxruntime`. The model is optional: the rest of the pipeline remains functional without it.

### Run on Windows PowerShell
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
ffprobe -version
ffmpeg -version
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open:
```text
http://127.0.0.1:8000
```

### Run on Linux/macOS
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
ffprobe -version
ffmpeg -version
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### CLI
```bash
python run.py ./evidence/suspected.mp4 --description "controlled demonstration"
```

### Judge demo
1. Open the GUI.
2. Upload a controlled test video.
3. Show the original SHA-256 immediately.
4. Point to the parallel agent grid.
5. Open individual observations and show alternatives/limitations.
6. Show AASIST raw audio signal if the model is installed.
7. Show competing hypotheses and contradictions.
8. Generate the JSON forensic package.
9. Open the Markdown report.
10. Sign off only after explaining that automated findings remain subject to examiner review.

### Important scientific positioning
Do not demo this as "the AI says 97% fake".
The stronger forensic story is:
- exact evidence hash,
- reproducible measurements,
- independent observation families,
- correlated-detector handling,
- explicit benign alternatives,
- contradiction visibility,
- provenance,
- missing-evidence analysis,
- human review,
- complete audit trail.

NIST's current forensic deepfake work emphasizes validation under realistic conditions and robustness to post-processing/generalization. The evaluation folder should therefore include benign transformations such as resizing, re-encoding, compression, frame-rate conversion and audio normalization.

### Legal layer
Legal output is deliberately conservative. Candidate provisions must come from a versioned approved ruleset and must be reviewed by a qualified person. The supplied Plane C rules engine is retained under `core/plane_c`.

For electronic evidence in India, the Bharatiya Sakshya Adhiniyam, 2023 contains section 63 provisions and a certificate schedule referencing device/source details and hash values. The system stores those technical fields but never fabricates a statutory certificate or signs one on behalf of an investigator.

### Folder layout
```text
EMAFIG_BOB_FINAL/
├── app/
│   ├── main.py
│   ├── engine.py
│   ├── bob.py
│   ├── schemas.py
│   ├── store.py
│   ├── agents/
│   └── ui/
├── core/plane_c/             # supplied Plane C implementation
├── .bob/                     # supplied reasoning skills + new integration skills
├── models/audio/             # optional AASIST ONNX model
├── cases/
├── reports/
├── scripts/
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

### Security
Uploaded media is untrusted:
- original is copied once and treated as immutable;
- all processing occurs on derivatives/workspace;
- subprocesses have timeouts;
- no uploaded file is executed;
- Bob is not granted shell/database/delete privileges;
- failures are retained rather than silently hidden;
- report contains limitations and tool availability.

This is a hackathon/research implementation, not a certified forensic product.


## IBM Bob — recommended integration path

For the IBM Bob IDE workflow, use the included MCP server rather than trying to make the Python application call a private/undocumented Bob endpoint.

Project configuration:
```text
.bob/mcp.json
```

Server:
```text
mcp_server.py
```

Bob launches the local server over STDIO and receives bounded forensic tools. This follows IBM Bob's documented project-scope MCP configuration and local STDIO transport model.

The available Bob tools are:
```text
list_cases
get_case
get_agent_status
get_observations
get_hypotheses
get_contradictions
get_missing_evidence
verify_audit_ledger
start_investigation
review_observation
generate_report
sign_off_case
```

Recommended role split:
```text
IBM Bob = reasoning / orchestration / natural-language investigation control
EMAFIG = deterministic forensic execution / provenance / audit / reports
Investigator = evidence acceptance / rejection / final sign-off
```

On Windows, install:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Then open the project in IBM Bob, enable MCP, and confirm `emafg-forensics` is connected.

Detailed Windows setup:
```text
docs/BOB_MCP_WINDOWS.md
```
