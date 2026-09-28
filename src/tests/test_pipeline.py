
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


import shutil, subprocess, pytest


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe required")
def test_temporal_bframe_reordering_is_not_an_anomaly(tmp_path):
    """Regression: H.264 B-frame decode-order PTS must not be flagged as timing anomalies."""
    clip = tmp_path / "clean.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x180:rate=25",
                    "-c:v", "libx264", "-bf", "2", "-pix_fmt", "yuv420p", str(clip)], check=True)
    from app.agents import temporal
    out = tmp_path / "out"; out.mkdir()
    obs, _, warns = temporal.run(clip, out, "EVD-test")
    assert not warns
    cadence = [o for o in obs if o.type == "temporal.cadence"][0]
    assert cadence.measurement["anomaly_count"] == 0
    assert abs(cadence.measurement["median_interval_s"] - 0.04) < 1e-3


def test_face_cascade_loader_does_not_shadow_cv2():
    """Regression: a function-level 'import cv2.data' made cv2 a local name (UnboundLocalError on OpenCV 4)."""
    import inspect
    from app.agents import visual
    assert "import cv2.data" not in inspect.getsource(visual._load_face_cascade)
    visual._load_face_cascade()  # must not raise


def test_ui_escapes_case_list_filename():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app/ui/index.html").read_text(encoding="utf-8")
    assert "${esc(c.filename)}" in html and "<div class=\"muted\">${c.filename}</div>" not in html
