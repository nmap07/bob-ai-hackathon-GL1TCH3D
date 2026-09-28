"""
tests/test_visual_video.py
Visual forensics pipeline tests for video inputs.
"""
import asyncio
import io
import os
import struct
import tempfile
from pathlib import Path

import pytest

from app.store import CaseStore
from app.engine import InvestigationEngine
from app.agents import visual


def _make_video_mp4(tmp_path: Path, duration_s: float = 2.0,
                    width: int = 320, height: int = 240,
                    fps: int = 10) -> Path | None:
    """
    Create a minimal MP4 test video using ffmpeg.
    Returns None if ffmpeg is not available.
    """
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    out = tmp_path / "test.mp4"
    from app.forensics.tooling import run_tool
    result = run_tool([
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=blue:size={width}x{height}:rate={fps}",
        "-t", str(duration_s),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(out),
    ], timeout=30)
    return out if out.exists() and out.stat().st_size > 0 else None


def _make_video_no_audio(tmp_path: Path) -> Path | None:
    """Create a video with video-only track (no audio)."""
    return _make_video_mp4(tmp_path)  # ffmpeg color source has no audio


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"),
                    reason="ffmpeg not available")
def test_mp4_video_pipeline(tmp_path):
    """MP4 video: visual agent must complete and produce frame_sample observation."""
    vid = _make_video_mp4(tmp_path)
    if vid is None:
        pytest.skip("ffmpeg could not create test video")

    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(vid, "test mp4"))

    ar = c.agent_runs["visual-forensics"]
    assert ar.status in {"completed", "completed_with_warnings"}, (
        f"visual-forensics must not fail for MP4; got status={ar.status!r}, error={ar.error!r}"
    )
    types = {o.type for o in c.observations if o.agent_id == "visual-forensics"}
    assert "visual.video_frame_sample" in types
    assert "visual.face_detection" in types


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"),
                    reason="ffmpeg not available")
def test_video_without_audio(tmp_path):
    """Video without audio: av-sync should be not_applicable or completed_with_warnings."""
    vid = _make_video_no_audio(tmp_path)
    if vid is None:
        pytest.skip("ffmpeg could not create test video")

    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(vid, "video no audio"))
    # av-sync can be not_applicable or completed_with_warnings for no-audio video
    ar_av = c.agent_runs["av-sync-analysis"]
    assert ar_av.status in {"not_applicable", "completed_with_warnings", "completed"}


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"),
                    reason="ffmpeg not available")
def test_video_frame_manifest(tmp_path):
    """Video: frame_manifest.json artifact must be written and hashable."""
    vid = _make_video_mp4(tmp_path)
    if vid is None:
        pytest.skip("ffmpeg could not create test video")

    out = tmp_path / "artifacts"
    out.mkdir()
    obs, arts, warnings = visual.run(vid, out, "EVD-test", "video")

    # Must have a frame_manifest.json artifact
    manifest_art = next((a for a in arts if "frame_manifest" in a["path"]), None)
    assert manifest_art is not None, "frame_manifest.json artifact must be written"
    assert Path(manifest_art["path"]).exists()
    assert manifest_art["sha256"]

    # Must have sampled at least 1 frame
    types = {o.type for o in obs}
    assert "visual.video_frame_sample" in types


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"),
                    reason="ffmpeg not available")
def test_video_frame_hashes(tmp_path):
    """Every extracted frame PNG must have a sha256 and sha512 in the manifest."""
    import json
    vid = _make_video_mp4(tmp_path)
    if vid is None:
        pytest.skip("ffmpeg could not create test video")

    out = tmp_path / "artifacts"
    out.mkdir()
    visual.run(vid, out, "EVD-hash", "video")

    manifest_path = out / "frame_manifest.json"
    if not manifest_path.exists():
        pytest.skip("frame_manifest.json not written")

    manifest = json.loads(manifest_path.read_text())
    for frame in manifest.get("frames", []):
        assert frame.get("sha256"), f"Frame {frame.get('frame_index')} missing sha256"
        assert frame.get("sha512"), f"Frame {frame.get('frame_index')} missing sha512"


def test_visual_direct_video_no_ffmpeg(tmp_path, monkeypatch):
    """Visual agent must fall back gracefully when ffmpeg/ffprobe is absent."""
    import shutil as _shutil

    # Create a minimal valid PNG (visual agent won't fail for image)
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(100, 100, 100)).save(buf, format="JPEG")
    src = tmp_path / "fake_video.mp4"
    # Write a decodable JPEG pretending to be MP4 (OpenCV handles gracefully)
    src.write_bytes(buf.getvalue())
    out = tmp_path / "artifacts"
    out.mkdir()

    # Patch resolve_executable to say ffprobe is unavailable
    import app.forensics.tooling as tooling
    original = tooling.resolve_executable
    def mock_resolve(name):
        if name in ("ffprobe", "ffmpeg"):
            return {"available": False, "path": None, "version": None, "error": "mocked absent"}
        return original(name)
    monkeypatch.setattr(tooling, "resolve_executable", mock_resolve)

    # Should warn about ffprobe, not raise
    try:
        obs, arts, warnings = visual.run(src, out, "EVD-novid", "video")
        # If it fails to extract frames, it should raise ValueError, not crash silently
    except ValueError as exc:
        assert "frames" in str(exc).lower() or "No frames" in str(exc)
    except Exception as exc:
        pytest.fail(f"Unexpected exception type: {type(exc).__name__}: {exc}")
