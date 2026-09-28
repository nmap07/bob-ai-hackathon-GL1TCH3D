
import asyncio, io
from pathlib import Path
from app.store import CaseStore
from app.engine import InvestigationEngine

def test_hash_and_image_pipeline(tmp_path):
    # Minimal 1x1 PNG.
    png=bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cf00000003000101")
    src=tmp_path/"x.png"; src.write_bytes(png)
    store=CaseStore(tmp_path/"cases")
    c=asyncio.run(InvestigationEngine(store).create_case(src,"test"))
    assert c.original.sha256
    assert c.original.sha512
    assert c.agent_runs["visual-forensics"].status in {"completed","completed_with_warnings","failed"}
    assert store.ledger(c.case_id).verify()["valid"]
