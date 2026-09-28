"""
app/agents/compression.py
Compression / re-encoding examiner (plan §6.5, P1-a).

IMAGE : error-level analysis (ELA) with block-level statistics, face-vs-background
        ELA ratio when a face is found, JPEG quality estimated from the
        quantisation tables.
VIDEO : GOP structure and frame-type pattern from ffprobe, mid-stream
        resolution changes.

Every metric is uncalibrated. Platform recompression produces the same
signals as tampering, so each observation carries those alternatives.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from app.schemas import Observation
from app.utils import new_id, sha256_file, sha512_file
from app.forensics.tooling import resolve_executable, run_tool

AGENT_ID = "compression-analysis"
VERSION = "3.0.0"

ELA_QUALITY = 90
ELA_BLOCK = 16
MAX_PROBE_SECONDS = 120

# libjpeg standard luminance quantisation table (quality 50), zig-zag agnostic.
_STD_LUMA = np.array([
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99], dtype=np.float64)


def _obs(type_, statement, measurement, evidence_id, **kw) -> Observation:
    return Observation(observation_id=new_id("OBS"), agent_id=AGENT_ID, agent_version=VERSION,
                       type=type_, statement=statement, measurement=measurement,
                       basis=[evidence_id], calibrated=False, **kw)


def _save_json(data, out: Path, prefix: str) -> dict:
    p = out / f"{prefix}_{new_id('RAW')}.json"
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return {"path": str(p), "sha256": sha256_file(p), "sha512": sha512_file(p), "type": "json"}


def _jpeg_quality(media: Path) -> int | None:
    """Estimate libjpeg quality from the luminance table; None for non-JPEG."""
    try:
        from PIL import Image
        with Image.open(media) as im:
            q = getattr(im, "quantization", None)
            if not q or 0 not in q:
                return None
            table = np.array(list(q[0])[:64], dtype=np.float64)
        scale = float(np.mean(table / _STD_LUMA) * 100.0)
        quality = (200.0 - scale) / 2.0 if scale <= 100 else 5000.0 / scale
        return int(round(max(1.0, min(100.0, quality))))
    except Exception:
        return None


def _block_means(diff: np.ndarray, b: int = ELA_BLOCK) -> np.ndarray:
    h, w = diff.shape
    h2, w2 = h // b * b, w // b * b
    if h2 == 0 or w2 == 0:
        return np.array([float(diff.mean())])
    return diff[:h2, :w2].reshape(h2 // b, b, w2 // b, b).mean(axis=(1, 3))


def _image(media: Path, out: Path, evidence_id: str):
    obs, arts, warnings = [], [], []
    bgr = cv2.imread(str(media))
    if bgr is None:
        try:
            from PIL import Image
            with Image.open(media) as im:
                bgr = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception as exc:
            raise ValueError(f"Could not decode image for compression analysis: {exc}")

    ok, enc = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, ELA_QUALITY])
    rec = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    diff = cv2.absdiff(bgr, rec).astype(np.float32).mean(axis=2)
    blocks = _block_means(diff)
    p50 = float(np.median(blocks)); p99 = float(np.percentile(blocks, 99))
    region_ratio = p99 / max(p50, 0.5)

    face_ratio = None
    face_bbox = None
    try:
        from app.agents.visual import _load_face_cascade, _detect_faces
        cascade = _load_face_cascade()
        faces = _detect_faces(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cascade, 0) if cascade is not None else []
        if faces:
            x, y, w, h = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])["bbox"]
            face_bbox = [x, y, w, h]
            mask = np.zeros(diff.shape, dtype=bool); mask[y:y + h, x:x + w] = True
            face_mean = float(diff[mask].mean()); bg_mean = float(diff[~mask].mean()) if (~mask).any() else 0.0
            face_ratio = face_mean / max(bg_mean, 1e-3)
    except Exception as exc:
        warnings.append(f"Face-region ELA skipped: {exc}")

    ela_png = out / f"ela_{new_id('DER')}.png"
    cv2.imwrite(str(ela_png), cv2.convertScaleAbs(diff, alpha=15))
    arts.append({"path": str(ela_png), "sha256": sha256_file(ela_png), "sha512": sha512_file(ela_png),
                 "type": "png", "parent": "original"})

    quality = _jpeg_quality(media)
    measurement = {
        "ela_quality": ELA_QUALITY, "ela_mean": round(float(diff.mean()), 4),
        "ela_block_p50": round(p50, 4), "ela_block_p99": round(p99, 4),
        "ela_region_ratio": round(region_ratio, 4),
        "face_background_ela_ratio": None if face_ratio is None else round(face_ratio, 4),
        "jpeg_estimated_quality": quality,
    }
    raw = {"agent": AGENT_ID, "version": VERSION, "measurement": measurement, "face_bbox": face_bbox,
           "ela_image": ela_png.name}
    arts.append(_save_json(raw, out, "compression_image"))
    obs.append(_obs(
        "compression.ela_screen",
        (f"Error-level analysis at JPEG q{ELA_QUALITY}: block p99/p50 ratio {region_ratio:.2f}"
         + (f"; face/background ELA ratio {face_ratio:.2f}" if face_ratio is not None else "")
         + (f"; estimated source JPEG quality {quality}." if quality else ".")),
        measurement, evidence_id,
        location={"bbox": face_bbox} if face_bbox else {},
        alternative_explanations=["platform recompression", "resaving at a different quality",
                                  "edges and texture detail", "resizing", "sharpening filters"],
        limitations=["ELA is a heuristic with known false positives; high-detail regions naturally show higher error levels.",
                     "Face/background ratio depends on the face detector's box."],
        not_tested=["comparison with an earlier-generation copy", "double-quantisation histogram analysis"],
    ))
    return obs, arts, warnings


def _video(media: Path, out: Path, evidence_id: str):
    obs, arts, warnings = [], [], []
    tool = resolve_executable("ffprobe")
    if not tool["available"]:
        return obs, arts, ["ffprobe not found; GOP/frame-type analysis unavailable."]
    cmd = [tool["path"], "-v", "quiet", "-print_format", "json", "-select_streams", "v:0",
           "-read_intervals", f"%+{MAX_PROBE_SECONDS}",
           "-show_entries", "frame=pict_type,key_frame,pkt_size,width,height", "-show_frames", str(media)]
    res = run_tool(cmd, timeout=240)
    arts.append(_save_json({"tool": "ffprobe", "version": tool["version"], "command": cmd,
                            "returncode": res["returncode"], "stdout": res["stdout"], "stderr": res["stderr"]},
                           out, "compression_frames"))
    if res["returncode"] != 0:
        return obs, arts, [f"ffprobe frame analysis failed (rc={res['returncode']})."]
    frames = json.loads(res["stdout"] or "{}").get("frames", [])
    if not frames:
        return obs, arts, ["No video frames reported by ffprobe."]

    types = [f.get("pict_type", "?") for f in frames]
    i_idx = [i for i, t in enumerate(types) if t == "I"]
    gops = [b - a for a, b in zip(i_idx, i_idx[1:])]
    median_gop = float(np.median(gops)) if gops else None
    irregular = [{"gop_index": j, "length": g, "frame_range": [i_idx[j], i_idx[j + 1]]}
                 for j, g in enumerate(gops) if median_gop and abs(g - median_gop) > 0.3 * median_gop]
    frac = (len(irregular) / len(gops)) if gops else None
    obs.append(_obs(
        "compression.gop_structure",
        (f"{len(frames)} frames examined (first {MAX_PROBE_SECONDS}s): {types.count('I')} I, {types.count('P')} P, "
         f"{types.count('B')} B; {len(gops)} GOPs, median length {median_gop}, {len(irregular)} irregular."),
        {"frames_examined": len(frames), "i_frames": types.count("I"), "p_frames": types.count("P"),
         "b_frames": types.count("B"), "gop_count": len(gops), "gop_median": median_gop,
         "gop_irregular_count": len(irregular), "gop_irregular_fraction": None if frac is None else round(frac, 4),
         "irregular_gops": irregular[:50]},
        evidence_id,
        location={"frame_start": irregular[0]["frame_range"][0], "frame_end": irregular[-1]["frame_range"][1]} if irregular else {},
        alternative_explanations=["scene-cut keyframes inserted by the encoder", "platform transcoding",
                                  "variable bitrate encoding", "editing/trimming"],
        limitations=["GOP irregularity is an indicator of re-encoding or editing, not of face manipulation."],
        not_tested=["double-compression analysis of macroblock QP distribution"],
    ))

    resolutions = sorted({f"{f.get('width')}x{f.get('height')}" for f in frames if f.get("width")})
    if len(resolutions) > 1:
        obs.append(_obs(
            "compression.resolution_change",
            f"Frame resolution changes within the stream: {', '.join(resolutions)}.",
            {"resolutions": resolutions, "distinct_resolutions": len(resolutions)}, evidence_id,
            alternative_explanations=["adaptive-bitrate streaming capture", "screen recording", "editing/concatenation"],
            limitations=["Resolution changes are common in screen recordings and streamed video."],
        ))
    return obs, arts, warnings


def run(media: Path, out: Path, evidence_id: str, media_type: str):
    out.mkdir(parents=True, exist_ok=True)
    if media_type == "image":
        return _image(media, out, evidence_id)
    if media_type == "video":
        return _video(media, out, evidence_id)
    return [], [], ["Compression analysis applies to image and video evidence only."]
