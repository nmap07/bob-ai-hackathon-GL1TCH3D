
from __future__ import annotations
import os, json, shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.store import CaseStore
from app.engine import InvestigationEngine
from app.schemas import ReviewRequest, SignoffRequest

ROOT=Path(__file__).resolve().parents[1]
STORE=CaseStore(ROOT/"cases")
ENGINE=InvestigationEngine(STORE)

app=FastAPI(title="EMAFIG — Bob Deepfake Forensic Investigation",version="2.0.0")
app.mount("/static",StaticFiles(directory=ROOT/"app/static"),name="static")

@app.get("/",response_class=HTMLResponse)
def home():
    return (ROOT/"app/ui/index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"ok":True,"service":"emafg","bob_mode":ENGINE.bob.mode}

@app.get("/api/cases")
def cases():
    return [c.model_dump() for c in STORE.list_cases()]

@app.get("/api/cases/{case_id}")
def get_case(case_id:str):
    c=STORE.load(case_id)
    if not c: raise HTTPException(404,"case not found")
    return c.model_dump()

@app.post("/api/cases")
async def create_case(file:UploadFile=File(...),description:str=Form("")):
    temp=ROOT/"working_uploads"; temp.mkdir(exist_ok=True)
    tmp=temp/(Path(file.filename or "evidence.bin").name)
    with tmp.open("wb") as f:
        while chunk:=await file.read(1024*1024): f.write(chunk)
    try:
        c=await ENGINE.create_case(tmp,description or None)
        return c.model_dump()
    finally:
        tmp.unlink(missing_ok=True)

@app.post("/api/cases/{case_id}/review")
def review(case_id:str,req:ReviewRequest):
    c=STORE.load(case_id)
    if not c: raise HTTPException(404,"case not found")
    return ENGINE.review(c,req.observation_id,req.status,req.reviewer,req.reason).model_dump()

@app.post("/api/cases/{case_id}/report")
def report(case_id:str):
    c=STORE.load(case_id)
    if not c: raise HTTPException(404,"case not found")
    return ENGINE.generate_report(c).model_dump()

@app.post("/api/cases/{case_id}/signoff")
def signoff(case_id:str,req:SignoffRequest):
    c=STORE.load(case_id)
    if not c: raise HTTPException(404,"case not found")
    return ENGINE.generate_report(c,req.model_dump()).model_dump()

@app.get("/api/cases/{case_id}/report/{kind}")
def report_file(case_id:str,kind:str):
    c=STORE.load(case_id)
    if not c: raise HTTPException(404,"case not found")
    p=c.reports.get(kind)
    if not p or not Path(p).exists(): raise HTTPException(404,"report not generated")
    return FileResponse(p,filename=Path(p).name)
