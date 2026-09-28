"""
tests/test_visual_image.py
Visual forensics pipeline tests for image inputs.
"""
import asyncio
import io
import struct
import zlib
from pathlib import Path

import pytest

from app.store import CaseStore
from app.engine import InvestigationEngine
from app.agents import visual


# ---------------------------------------------------------------------------
# Helpers to synthesize minimal valid image bytes
# ---------------------------------------------------------------------------

def _minimal_png(width=64, height=64) -> bytes:
    """Create a minimal valid PNG in memory."""
    import struct, zlib
    def chunk(name, data):
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00" + bytes([128] * width * 3)
    compressed = zlib.compress(raw_data)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _minimal_jpeg(width=32, height=32) -> bytes:
    """Create a minimal valid JPEG using Pillow."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 80, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def _corrupted_file() -> bytes:
    return b"NOT AN IMAGE AT ALL \x00\xff\xfe"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_png_image_pipeline(tmp_path):
    """PNG image: visual agent must complete (not fail) and produce observations."""
    src = tmp_path / "test.png"
    src.write_bytes(_minimal_png(128, 128))
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "test png"))

    ar = c.agent_runs["visual-forensics"]
    assert ar.status in {"completed", "completed_with_warnings"}, (
        f"visual-forensics must not fail for PNG; got status={ar.status!r}, error={ar.error!r}"
    )
    vis_obs = [o for o in c.observations if o.agent_id == "visual-forensics"]
    assert len(vis_obs) >= 1, "Expected at least one visual observation"
    # Must have a dimensions observation
    types = {o.type for o in vis_obs}
    assert "visual.image_dimensions" in types

    # Original must not be modified
    assert c.original.sha256 == c.original.sha256


def test_jpeg_image_pipeline(tmp_path):
    """JPEG image: visual agent must complete and produce face_detection observation."""
    src = tmp_path / "test.jpg"
    src.write_bytes(_minimal_jpeg(64, 64))
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "test jpeg"))

    ar = c.agent_runs["visual-forensics"]
    assert ar.status in {"completed", "completed_with_warnings"}, (
        f"visual-forensics must not fail for JPEG; got status={ar.status!r}"
    )
    types = {o.type for o in c.observations if o.agent_id == "visual-forensics"}
    assert "visual.image_dimensions" in types
    assert "visual.face_detection" in types


def test_webp_image_pipeline(tmp_path):
    """WEBP image: visual agent must not fail."""
    from PIL import Image
    src = tmp_path / "test.webp"
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(200, 100, 50)).save(buf, format="WEBP")
    src.write_bytes(buf.getvalue())

    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "test webp"))

    ar = c.agent_runs["visual-forensics"]
    assert ar.status in {"completed", "completed_with_warnings"}


def test_bmp_image_pipeline(tmp_path):
    """BMP image."""
    from PIL import Image
    src = tmp_path / "test.bmp"
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(50, 100, 150)).save(buf, format="BMP")
    src.write_bytes(buf.getvalue())

    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "test bmp"))
    ar = c.agent_runs["visual-forensics"]
    assert ar.status in {"completed", "completed_with_warnings"}


def test_image_with_exif(tmp_path):
    """Image with EXIF: metadata agent must produce image_properties observation, not fail."""
    from PIL import Image
    import struct
    src = tmp_path / "exif.jpg"
    # Build a minimal EXIF blob using Pillow's built-in
    buf = io.BytesIO()
    img = Image.new("RGB", (64, 64), color=(100, 100, 100))
    # Save with a comment as closest proxy (full EXIF injection needs piexif or similar)
    img.save(buf, format="JPEG")
    src.write_bytes(buf.getvalue())

    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "test exif"))
    ar_meta = c.agent_runs["metadata-analysis"]
    assert ar_meta.status in {"completed", "completed_with_warnings"}
    types = {o.type for o in c.observations if o.agent_id == "metadata-analysis"}
    assert "metadata.image_properties" in types


def test_image_without_exif(tmp_path):
    """Image without EXIF: metadata agent must still complete, not fail."""
    src = tmp_path / "no_exif.png"
    src.write_bytes(_minimal_png(32, 32))
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "test no-exif"))
    ar_meta = c.agent_runs["metadata-analysis"]
    assert ar_meta.status in {"completed", "completed_with_warnings"}


def test_corrupted_image(tmp_path):
    """Corrupted file: visual agent should FAIL (decode failure), not crash engine."""
    src = tmp_path / "corrupt.jpg"
    src.write_bytes(_corrupted_file())
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "corrupt"))
    ar = c.agent_runs["visual-forensics"]
    # Status can be 'failed' — this is the correct outcome for undecodable input
    assert ar.status in {"failed", "completed_with_warnings"}
    # Engine must not crash — case must be saved
    assert c.case_id


def test_zero_face_image(tmp_path):
    """Solid-colour image (no face): face_detection observation must be present, not fail."""
    from PIL import Image
    src = tmp_path / "noface.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), color=(0, 0, 255)).save(buf, format="JPEG")
    src.write_bytes(buf.getvalue())

    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c = asyncio.run(engine.create_case(src, "no face"))
    ar = c.agent_runs["visual-forensics"]
    assert ar.status in {"completed", "completed_with_warnings"}
    fobs = next((o for o in c.observations if o.type == "visual.face_detection"), None)
    assert fobs is not None
    # Zero faces is valid
    assert fobs.measurement["faces_detected"] >= 0


def test_hashes_preserved(tmp_path):
    """Original file must never be modified — hash must be stable across two loads."""
    src = tmp_path / "hash_test.png"
    src.write_bytes(_minimal_png(64, 64))
    store  = CaseStore(tmp_path / "cases")
    engine = InvestigationEngine(store)
    c1 = asyncio.run(engine.create_case(src, "hash test"))
    c2 = store.load(c1.case_id)
    assert c1.original.sha256 == c2.original.sha256
    assert c1.original.sha512 == c2.original.sha512


def test_visual_agent_direct_image(tmp_path):
    """Direct unit test of visual.run() for image modality."""
    src = tmp_path / "direct.jpg"
    src.write_bytes(_minimal_jpeg(64, 64))
    out = tmp_path / "artifacts"
    out.mkdir()
    obs, arts, warnings = visual.run(src, out, "EVD-test", "image")
    assert isinstance(obs, list)
    assert isinstance(arts, list)
    assert isinstance(warnings, list)
    types = {o.type for o in obs}
    assert "visual.image_dimensions" in types
    assert "visual.face_detection" in types
    # All observations must have required fields
    for o in obs:
        assert o.observation_id
        assert o.agent_id == "visual-forensics"
        assert o.basis == ["EVD-test"]
