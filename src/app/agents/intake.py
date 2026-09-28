
from __future__ import annotations
from pathlib import Path
from app.schemas import Observation, AgentRun
from app.utils import utcnow, new_id, sha256_file, sha512_file, run_cmd, tool_version

import json, shutil
from app.utils import safe_name, media_type

AGENT_ID="forensic-intake"; VERSION="2.0.0"

def ingest(src: Path, case_dir: Path, case_id: str):
    name=safe_name(src.name)
    original=case_dir/"original"/name
    if original.exists(): raise ValueError("original already exists")
    shutil.copy2(src, original)
    return {
        "artifact_id":new_id("ART"), "path":str(original), "type":media_type(original),
        "size_bytes":original.stat().st_size, "sha256":sha256_file(original),
        "sha512":sha512_file(original)
    }
