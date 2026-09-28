from __future__ import annotations
import os, shutil, stat
from pathlib import Path
from app.utils import new_id, sha256_file, sha512_file, safe_name, media_type

AGENT_ID="forensic-intake"; VERSION="2.1.0"

def ingest(src: Path, case_dir: Path, case_id: str):
    """Copy the submitted file into original/, hash it, and make it read-only.

    The hash is computed on the source *and* on the stored copy; a mismatch
    means the copy is not faithful and intake fails.
    """
    name=safe_name(src.name) or "evidence.bin"
    original=case_dir/"original"/name
    if original.exists(): raise ValueError("original already exists")
    src_sha256=sha256_file(src)
    shutil.copy2(src, original)
    stored_sha256=sha256_file(original)
    if stored_sha256!=src_sha256:
        original.unlink(missing_ok=True)
        raise ValueError("stored copy hash does not match submitted file")
    read_only=True
    try:
        os.chmod(original, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        read_only=False
    return {
        "artifact_id":new_id("ART"), "path":str(original), "type":media_type(original),
        "size_bytes":original.stat().st_size, "sha256":stored_sha256,
        "sha512":sha512_file(original), "read_only":read_only,
    }

def verify(path: Path, expected_sha256: str) -> bool:
    """Re-verify the canonical source hash before any examiner reads the file (AGENTS.md rule 2)."""
    return path.exists() and sha256_file(path)==expected_sha256
