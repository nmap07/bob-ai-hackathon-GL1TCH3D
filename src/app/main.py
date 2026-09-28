"""
app/main.py
Local officer-workflow API + browser UI.

Security (plan §13): bind to 127.0.0.1; Host header allow-list (DNS-rebinding
protection); every state-changing request needs the per-run token that is
injected into the served page (X-EMAFIG-Token), which a cross-site page cannot
read or send.
"""
from __future__ import annotations

import os, secrets, shutil, tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import baselines
from app.engine import AGENTS, LEGAL_FACTS, CaseError, InvestigationEngine
from app.envelope import AGENT_TOOLS, tool_info
from app.schemas import (ACHAcceptRequest, ACHEditRequest, AnalystAssessmentRequest, BobPasteRequest,
                         BulkReviewRequest, EvidenceStatusRequest, IntakeDetails, LegalRequest,
                         OfficerObservationRequest, ReviewRequest, SignoffRequest, VerifyRequest)
from app.store import CaseStore
from core.plane_c.legal_engine import LegalRulesEngine

ROOT = Path(__file__).resolve().parents[1]
STORE = CaseStore(os.getenv("EMAFIG_CASES_DIR", ROOT / "cases"))
ENGINE = InvestigationEngine(STORE)
API_TOKEN = os.getenv("EMAFIG_API_TOKEN") or secrets.token_urlsafe(24)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "2048")) * 1024 * 1024
ALLOWED_HOSTS = [h.strip() for h in os.getenv("EMAFIG_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if h.strip()]

app = FastAPI(title="EMAFIG — Bob Deepfake Forensic Investigation", version="3.0.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def require_token(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get("x-emafig-token", ""), API_TOKEN):
            return JSONResponse({"detail": "missing or invalid X-EMAFIG-Token"}, status_code=403)
    return await call_next(request)


@app.exception_handler(CaseError)
async def case_error(_: Request, exc: CaseError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(TimeoutError)
async def busy(_: Request, exc: TimeoutError):
    return JSONResponse({"detail": "case is busy with another operation; retry shortly"}, status_code=409)


def _case(case_id):
    c = STORE.load(case_id)
    if not c: raise HTTPException(404, "case not found")
    return c

# ------------------------------------------------------------------ UI + reference data

@app.get("/", response_class=HTMLResponse)
def home():
    html = (ROOT / "app/ui/index.html").read_text(encoding="utf-8")
    return html.replace("__EMAFIG_TOKEN__", API_TOKEN)


@app.get("/api/health")
def health():
    tools = {n: tool_info(n).get("available", False) for n in sorted({t for ts in AGENT_TOOLS.values() for t in ts})}
    return {"ok": True, "service": "emafig", "bob_mode": ENGINE.bob.mode, "baseline_profile": baselines.PROFILE_ID,
            "baseline_version": baselines.PROFILE_VERSION, "tools": tools,
            "agents": [{"agent_id": a, "version": v, "media": sorted(m)} for a, v, m in AGENTS]}


@app.get("/api/baselines")
def baseline_profile():
    return baselines.profile_table()


@app.get("/api/legal/rules")
def legal_rules():
    spec = {k: ("boolean" if v is bool else list(v)) for k, v in LEGAL_FACTS.items()}
    return {**LegalRulesEngine().export_table(), "facts": spec}

# ------------------------------------------------------------------ cases

@app.get("/api/cases")
def cases():
    return [{"case_id": c.case_id, "filename": c.filename, "media_type": c.media_type, "status": c.status,
             "stage": c.stage, "updated_utc": c.updated_utc, "risk_score": (c.risk or {}).get("risk_score"),
             "band": (c.risk or {}).get("band"), "sealed": c.sealed} for c in STORE.list_cases()]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return _case(case_id).model_dump()


@app.post("/api/cases")
async def create_case(background: BackgroundTasks, file: UploadFile = File(...), description: str = Form(""),
                      case_id: str = Form(""), officer_name: str = Form(""), officer_id: str = Form(""),
                      how_received: str = Form(""), platform: str = Form(""), source_url: str = Form(""),
                      sender_id: str = Form(""), received_at: str = Form(""), seizure_memo_ref: str = Form(""),
                      device_details: str = Form(""), notes: str = Form("")):
    tmpdir = Path(tempfile.mkdtemp(prefix="emafig_upload_"))
    tmp = tmpdir / (Path(file.filename or "evidence.bin").name or "evidence.bin")
    size = 0
    try:
        with tmp.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"upload exceeds MAX_UPLOAD_MB={MAX_UPLOAD_BYTES // 1048576}")
                f.write(chunk)
        if size == 0: raise HTTPException(422, "empty file")
        details = IntakeDetails(officer_name=officer_name or None, officer_id=officer_id or None,
                                how_received=how_received or None, platform=platform or None,
                                source_url=source_url or None, sender_id=sender_id or None,
                                received_at=received_at or None, seizure_memo_ref=seizure_memo_ref or None,
                                device_details=device_details or None, notes=notes or None)
        c = ENGINE.start_case(tmp, description or None, case_id or None, details)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    background.add_task(ENGINE.run_analysis, c.case_id)
    return c.model_dump()

# ------------------------------------------------------------------ officer actions

@app.post("/api/cases/{case_id}/review")
def review(case_id: str, req: ReviewRequest):
    return ENGINE.review(case_id, req.observation_id, req.status, req.reviewer, req.reason).model_dump()


@app.post("/api/cases/{case_id}/review/bulk")
def review_bulk(case_id: str, req: BulkReviewRequest):
    return ENGINE.bulk_review(case_id, req.observation_ids, req.status, req.reviewer, req.reason).model_dump()


@app.post("/api/cases/{case_id}/observations")
def officer_observation(case_id: str, req: OfficerObservationRequest):
    return ENGINE.add_officer_observation(case_id, req.reviewer, req.type, req.statement, req.location,
                                         req.alternative_explanations).model_dump()


@app.post("/api/cases/{case_id}/ach/edit")
def ach_edit(case_id: str, req: ACHEditRequest):
    return ENGINE.edit_ach(case_id, req.group_id, req.hypothesis_id, req.value, req.reason, req.editor).model_dump()


@app.post("/api/cases/{case_id}/ach/accept")
def ach_accept(case_id: str, req: ACHAcceptRequest):
    return ENGINE.accept_ach(case_id, req.analyst).model_dump()


@app.post("/api/cases/{case_id}/evidence-status")
def evidence_status(case_id: str, req: EvidenceStatusRequest):
    return ENGINE.set_evidence_status(case_id, req.item, req.status, req.officer).model_dump()


@app.post("/api/cases/{case_id}/legal")
def legal(case_id: str, req: LegalRequest):
    return ENGINE.set_legal(case_id, req.officer, req.facts, req.confirmed_circumstances).model_dump()


@app.post("/api/cases/{case_id}/verify")
def verify(case_id: str, req: VerifyRequest):
    return ENGINE.verify_text(case_id, req.text)


@app.post("/api/cases/{case_id}/assessment")
def assessment(case_id: str, req: AnalystAssessmentRequest):
    return ENGINE.set_analyst_assessment(case_id, req.analyst, req.text).model_dump()


@app.post("/api/cases/{case_id}/reason")
async def rerun(case_id: str):
    return (await ENGINE.rerun_reasoning(case_id)).model_dump()


@app.post("/api/cases/{case_id}/bob/{mode}")
def paste_bob(case_id: str, mode: str, req: BobPasteRequest):
    return ENGINE.paste_bob_reply(case_id, mode, req.reply, req.officer).model_dump()


@app.get("/api/cases/{case_id}/bob/{mode}/prompt")
def bob_prompt(case_id: str, mode: str):
    p = STORE.case_dir(case_id) / "artifacts" / "bob_prompts" / f"{Path(mode).name}.txt"
    if not p.exists(): raise HTTPException(404, "no saved prompt for this mode (BOB_MODE=manual writes them)")
    return FileResponse(p, media_type="text/plain; charset=utf-8")


@app.post("/api/cases/{case_id}/report")
def report(case_id: str):
    return ENGINE.generate_report(case_id).model_dump()


@app.post("/api/cases/{case_id}/signoff")
def signoff(case_id: str, req: SignoffRequest):
    return ENGINE.signoff(case_id, req.reviewer, req.role, req.statement).model_dump()


@app.get("/api/cases/{case_id}/report/{kind}")
def report_file(case_id: str, kind: str, download: bool = False):
    c = _case(case_id)
    p = c.reports.get(kind)
    if not p or not Path(p).exists(): raise HTTPException(404, "report not generated")
    p = Path(p)
    if not p.resolve().is_relative_to(STORE.case_dir(case_id).resolve()): raise HTTPException(403, "outside case")
    mt = {".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".csv": "text/csv; charset=utf-8",
          ".json": "application/json"}.get(p.suffix, "application/octet-stream")
    return FileResponse(p, media_type=mt, filename=p.name if download else None)


@app.get("/api/cases/{case_id}/ledger")
def ledger(case_id: str):
    _case(case_id)
    led = STORE.ledger(case_id)
    return {"verification": led.verify(), "entries": led.entries()}


@app.get("/api/cases/{case_id}/ledger/verify")
def ledger_verify(case_id: str):
    _case(case_id)
    return STORE.ledger(case_id).verify()
