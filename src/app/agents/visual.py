"""
app/agents/visual.py
Robust modality-independent visual forensics pipeline.

IMAGE PATH:
  decode (Pillow + OpenCV) → validate dimensions → face detection (layered, graceful)
  → facial region analysis → artifact screening → frequency screening
  → noise/color screening → structured observations → artifact files + hashes

VIDEO PATH:
  ffprobe validation → deterministic bounded frame sampling → face detection/tracking
  → frame-level analysis → temporal consistency → structured observations

NEVER fails solely because:
  - ffprobe/ffmpeg is absent (images don't need it)
  - Haar XML is missing (falls back gracefully)
  - Optional ML model is absent
  - Face count is zero (observation, not failure)

Only FAILS on:
  - Unreadable/corrupted/decode failure
  - Unsupported file with no fallback
  - Fatal internal exception with no recovery path
"""
from __future__ import annotations

import json
import math
import time
import traceback
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.schemas import Observation
from app.utils import new_id, sha256_file, sha512_file, utcnow
from app.forensics.tooling import resolve_executable, run_tool

AGENT_ID = "visual-forensics"
VERSION  = "2.1.0"

MAX_FRAMES        = 32
VIDEO_FRAME_LIMIT = 32

# Supported extensions
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".m2ts", ".3gp"}


# ---------------------------------------------------------------------------
# Observation helpers
# ---------------------------------------------------------------------------

def _obs(type_: str, statement: str, measurement: dict, evidence_id: str,
         location: dict | None = None,
         supports: list[str] | None = None,
         contradicts: list[str] | None = None,
         alt_expl: list[str] | None = None,
         limitations: list[str] | None = None,
         calibrated: bool = False) -> Observation:
    return Observation(
        observation_id=new_id("OBS"),
        agent_id=AGENT_ID,
        agent_version=VERSION,
        type=type_,
        statement=statement,
        location=location or {},
        measurement=measurement,
        basis=[evidence_id],
        supports=supports or [],
        contradicts=contradicts or [],
        alternative_explanations=alt_expl or [],
        limitations=limitations or [],
        calibrated=calibrated,
    )


def _save_artifact(data: Any, out: Path, prefix: str) -> dict:
    raw = out / f"{prefix}_{new_id('RAW')}.json"
    raw.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return {"path": str(raw), "sha256": sha256_file(raw), "sha512": sha512_file(raw), "type": "json"}


# ---------------------------------------------------------------------------
# Face detection — layered, graceful
# ---------------------------------------------------------------------------

def _load_face_cascade() -> cv2.CascadeClassifier | None:
    """
    Try every known path for the frontal-face Haar cascade.
    Returns None if not found — callers must handle this gracefully.
    """
    # 1. cv2.data attribute (works when cascade data is bundled)
    try:
        candidate = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if Path(candidate).is_file():
            cc = cv2.CascadeClassifier(candidate)
            if not cc.empty():
                return cc
    except Exception:
        pass

    # 2. Walk known Windows site-packages locations
    import sys
    for site in sys.path:
        for rel in [
            "cv2/data/haarcascade_frontalface_default.xml",
            "share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
        ]:
            p = Path(site) / rel
            if p.is_file():
                cc = cv2.CascadeClassifier(str(p))
                if not cc.empty():
                    return cc

    return None


def _detect_faces(gray_img: np.ndarray, cascade: cv2.CascadeClassifier | None,
                  frame_idx: int) -> list[dict]:
    """Detect faces; returns list of bbox dicts. Never raises."""
    if cascade is None or cascade.empty():
        return []
    try:
        faces = cascade.detectMultiScale(gray_img, scaleFactor=1.1, minNeighbors=5,
                                          minSize=(30, 30))
        if not isinstance(faces, np.ndarray) or len(faces) == 0:
            return []
        return [{"frame": frame_idx, "bbox": [int(x), int(y), int(w), int(h)]}
                for x, y, w, h in faces]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Per-frame analysis
# ---------------------------------------------------------------------------

def _laplacian_var(region: np.ndarray) -> float:
    """Laplacian variance (sharpness proxy). Returns 0 on error."""
    try:
        if region.size == 0:
            return 0.0
        return float(np.var(cv2.Laplacian(region, cv2.CV_64F)))
    except Exception:
        return 0.0


def _noise_estimate(region: np.ndarray) -> float:
    """Estimate local noise using median-absolute-deviation on high-pass."""
    try:
        if region.size == 0:
            return 0.0
        blurred = cv2.GaussianBlur(region, (5, 5), 0)
        diff = region.astype(np.float32) - blurred.astype(np.float32)
        return float(np.std(diff))
    except Exception:
        return 0.0


def _analyze_face_region(gray: np.ndarray, bgr: np.ndarray,
                          bbox: list[int]) -> dict:
    x, y, w, h = bbox
    H, W = gray.shape[:2]
    # Face ROI with small margin
    margin = 10
    fy1, fy2 = max(0, y - margin), min(H, y + h + margin)
    fx1, fx2 = max(0, x - margin), min(W, x + w + margin)
    face_gray = gray[y:y+h, x:x+w]
    roi_gray  = gray[fy1:fy2, fx1:fx2]

    face_lap   = _laplacian_var(face_gray)
    boundary_lap = _laplacian_var(roi_gray)
    face_noise = _noise_estimate(face_gray)

    ratio = boundary_lap / face_lap if face_lap > 0 else 0.0

    # Color stats around boundary
    face_bgr = bgr[y:y+h, x:x+w]
    color_mean = [float(v) for v in cv2.mean(face_bgr)[:3]]

    return {
        "face_laplacian":     round(face_lap, 3),
        "boundary_laplacian": round(boundary_lap, 3),
        "boundary_face_ratio": round(ratio, 4),
        "face_noise_std":     round(face_noise, 3),
        "face_color_mean_bgr": color_mean,
        "face_size_px":        [w, h],
    }


def _frequency_screening(gray: np.ndarray) -> dict:
    """DCT-based frequency energy distribution screening."""
    try:
        h, w = gray.shape[:2]
        # Work on a 256x256 center crop to keep computation bounded
        sz = 256
        cy, cx = h // 2, w // 2
        half = sz // 2
        crop = gray[max(0, cy-half):cy+half, max(0, cx-half):cx+half]
        crop = cv2.resize(crop, (sz, sz))
        f   = np.fft.fft2(crop.astype(np.float32))
        mag = np.abs(np.fft.fftshift(f))
        total = float(np.sum(mag)) or 1.0
        # High-frequency quadrant (outer 25%)
        q = sz // 4
        hf = mag[q:sz-q, q:sz-q]  # actually middle — swap for proper HF
        # Proper HF: corners
        corners = (mag[:q, :q].sum() + mag[:q, sz-q:].sum() +
                   mag[sz-q:, :q].sum() + mag[sz-q:, sz-q:].sum())
        hf_ratio = float(corners) / total
        return {
            "fft_high_freq_ratio": round(hf_ratio, 6),
            "fft_total_energy":    round(total, 2),
        }
    except Exception:
        return {}


def _block_artifact_screen(gray: np.ndarray) -> dict:
    """Screen for JPEG block-boundary artifacts (8-px grid)."""
    try:
        h, w = gray.shape[:2]
        if h < 16 or w < 16:
            return {}
        g = gray.astype(np.float32)
        # Horizontal block boundaries
        h_diffs = [abs(float(np.mean(g[r, :]) - np.mean(g[r-1, :])))
                   for r in range(8, h, 8) if r < h]
        non_boundary_h = [abs(float(np.mean(g[r, :]) - np.mean(g[r-1, :])))
                          for r in range(1, h, 1) if r % 8 != 0 and r < h]
        block_score = (float(np.mean(h_diffs)) / (float(np.mean(non_boundary_h)) + 1e-6)
                       if h_diffs and non_boundary_h else 0.0)
        return {"block_artifact_score": round(block_score, 4)}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Frame extraction for video
# ---------------------------------------------------------------------------

def _extract_frames_video(media: Path, max_frames: int = MAX_FRAMES) -> tuple[list[tuple[int, float, np.ndarray]], list[str]]:
    """
    Deterministic bounded frame extraction from video using OpenCV.
    Returns list of (frame_index, timestamp_s, bgr_array) and warnings.
    """
    warnings: list[str] = []
    frames: list[tuple[int, float, np.ndarray]] = []

    try:
        cap = cv2.VideoCapture(str(media))
        if not cap.isOpened():
            warnings.append(f"OpenCV could not open video: {media.name}")
            return frames, warnings

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps   = cap.get(cv2.CAP_PROP_FPS) or 25.0

        if total <= 0:
            # Unknown length — read sequentially up to max_frames
            idx = 0
            while len(frames) < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                ts = idx / fps
                frames.append((idx, round(ts, 4), frame))
                idx += 1
        else:
            # Evenly distributed samples
            step = max(1, total // max_frames)
            positions = list(range(0, total, step))[:max_frames]
            for pos in positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ok, frame = cap.read()
                if ok:
                    ts = pos / fps
                    frames.append((pos, round(ts, 4), frame))

        cap.release()
    except Exception as exc:
        warnings.append(f"Frame extraction error: {exc}")

    return frames, warnings


# ---------------------------------------------------------------------------
# Frame manifest
# ---------------------------------------------------------------------------

def _write_frame_manifest(frames: list[tuple[int, float, np.ndarray]],
                           saved_frames: list[dict],
                           out: Path, evidence_id: str) -> dict:
    manifest = {
        "evidence_id":   evidence_id,
        "agent_id":      AGENT_ID,
        "agent_version": VERSION,
        "created_utc":   utcnow(),
        "frame_count":   len(saved_frames),
        "frames":        saved_frames,
    }
    path = out / "frame_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return {"path": str(path), "sha256": sha256_file(path), "type": "json"}


# ---------------------------------------------------------------------------
# IMAGE pipeline
# ---------------------------------------------------------------------------

def _run_image(media: Path, out: Path, evidence_id: str):
    obs:      list[Observation] = []
    arts:     list[dict]        = []
    warnings: list[str]         = []
    stages:   list[str]         = []

    # --- Stage: decode ---
    stages.append("decode")
    bgr = None
    try:
        # Prefer Pillow → convert to numpy for OpenCV compatibility
        from PIL import Image as PILImage
        import numpy as _np
        pil_img = PILImage.open(str(media)).convert("RGB")
        bgr = cv2.cvtColor(_np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as pil_exc:
        # Fallback to OpenCV native
        try:
            bgr = cv2.imread(str(media))
        except Exception as cv_exc:
            warnings.append(f"Pillow decode: {pil_exc}; cv2 decode: {cv_exc}")

    if bgr is None or bgr.size == 0:
        # Complete decode failure — this is a legitimate FAILED condition
        raise ValueError(f"Could not decode image '{media.name}' with Pillow or OpenCV.")

    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    stages.append("decode_ok")

    # --- Stage: validate dimensions ---
    stages.append("dimensions")
    obs.append(_obs(
        "visual.image_dimensions",
        f"Image decoded: {w}×{h} px, {media.stat().st_size} bytes.",
        {"width": w, "height": h, "channels": bgr.shape[2] if bgr.ndim == 3 else 1,
         "file_size_bytes": media.stat().st_size},
        evidence_id,
        limitations=["Image dimensions alone are not indicative of manipulation."],
    ))

    # --- Stage: face detection (graceful) ---
    stages.append("face_detection")
    cascade = None
    cascade_warning = None
    try:
        cascade = _load_face_cascade()
        if cascade is None:
            cascade_warning = (
                "Haar cascade XML not found in OpenCV data directory. "
                "Face detection skipped. Install opencv-contrib-python or "
                "place haarcascade_frontalface_default.xml in cv2/data/."
            )
            warnings.append(cascade_warning)
    except Exception as exc:
        cascade_warning = f"Face detector load failed: {exc}"
        warnings.append(cascade_warning)

    face_detections: list[dict] = []
    if cascade is not None:
        face_detections = _detect_faces(gray, cascade, frame_idx=0)

    face_measurements = {
        "frames_examined":    1,
        "faces_detected":     len(face_detections),
        "face_detection_rate": len(face_detections),
        "cascade_available":  cascade is not None,
    }
    if cascade_warning:
        face_measurements["cascade_warning"] = cascade_warning

    obs.append(_obs(
        "visual.face_detection",
        (f"Detected {len(face_detections)} face instance(s) in the image."
         if cascade is not None
         else "Face detection was not performed; Haar cascade unavailable."),
        face_measurements,
        evidence_id,
        alt_expl=["occlusion", "extreme pose", "low resolution", "non-human subjects",
                  "side profile", "mask/glasses"],
        limitations=[
            "Haar-based face detection is a screening signal only.",
            "Zero detections do not indicate absence of a person.",
            "Face detection failure does not indicate manipulation.",
        ],
    ))

    # --- Stage: facial region analysis ---
    stages.append("face_analysis")
    boundary_scores: list[float] = []

    for fd in face_detections:
        bbox = fd["bbox"]
        try:
            region_metrics = _analyze_face_region(gray, bgr, bbox)
            boundary_scores.append(region_metrics["boundary_face_ratio"])

            obs.append(_obs(
                "visual.face_boundary_screen",
                (f"Face at bbox {bbox}: boundary/face Laplacian ratio "
                 f"{region_metrics['boundary_face_ratio']:.4f}."),
                region_metrics,
                evidence_id,
                location={"frame": 0, "bbox": bbox},
                alt_expl=["compression", "resizing", "denoising",
                          "focus variation", "lighting", "vignetting"],
                limitations=[
                    "This measurement is a screening metric.",
                    "Ratio is not calibrated to a probability of manipulation.",
                ],
            ))
        except Exception as exc:
            warnings.append(f"Face region analysis failed for bbox {bbox}: {exc}")

    if len(boundary_scores) >= 2:
        mean_r = float(np.mean(boundary_scores))
        std_r  = float(np.std(boundary_scores))
        cv_r   = std_r / mean_r if mean_r > 0 else 0.0
        obs.append(_obs(
            "visual.face_boundary_variation",
            f"Face-boundary edge strength varied across {len(boundary_scores)} detections "
            f"(coefficient of variation {cv_r:.4f}).",
            {"mean_ratio": round(mean_r, 4), "std_ratio": round(std_r, 4),
             "coefficient_of_variation": round(cv_r, 4),
             "face_count": len(boundary_scores)},
            evidence_id,
            supports=["H2", "H5"] if cv_r > 0.5 else [],
            alt_expl=["compression", "resizing", "focus changes", "lighting changes"],
            limitations=["Coefficient of variation is not calibrated to manipulation probability."],
        ))

    # --- Stage: image-level artifact screening ---
    stages.append("artifact_screen")
    whole_lap  = _laplacian_var(gray)
    whole_noise = _noise_estimate(gray)
    obs.append(_obs(
        "visual.image_sharpness_screen",
        f"Whole-image Laplacian variance (sharpness proxy): {whole_lap:.2f}.",
        {"laplacian_variance": round(whole_lap, 3),
         "noise_std": round(whole_noise, 3)},
        evidence_id,
        alt_expl=["focus", "motion blur", "resize", "denoising",
                  "codec quantization", "source-camera processing"],
        limitations=["Sharpness screening is not a deepfake classifier."],
    ))

    # --- Stage: frequency screening ---
    stages.append("frequency_screen")
    try:
        freq = _frequency_screening(gray)
        if freq:
            obs.append(_obs(
                "visual.frequency_screen",
                f"FFT high-frequency energy ratio: {freq.get('fft_high_freq_ratio', 'N/A')}.",
                freq,
                evidence_id,
                alt_expl=["compression", "blur", "noise reduction", "upscaling"],
                limitations=["Frequency domain screening is not specific to synthetic generation."],
            ))
    except Exception as exc:
        warnings.append(f"Frequency screening failed: {exc}")

    # --- Stage: block artifact screen ---
    stages.append("block_screen")
    try:
        block = _block_artifact_screen(gray)
        if block:
            obs.append(_obs(
                "visual.block_artifact_screen",
                f"JPEG-block artifact score: {block.get('block_artifact_score', 'N/A')}.",
                block,
                evidence_id,
                alt_expl=["JPEG compression", "transcoding", "re-encoding"],
                limitations=["Block artifact score is indicative only, not diagnostic."],
            ))
    except Exception as exc:
        warnings.append(f"Block artifact screen failed: {exc}")

    # --- Save raw data artifact ---
    raw_data = {
        "agent":       AGENT_ID,
        "version":     VERSION,
        "media":       media.name,
        "stages_completed": stages,
        "face_detections": face_detections,
        "warnings":    warnings,
    }
    arts.append(_save_artifact(raw_data, out, "visual_image"))

    return obs, arts, warnings


# ---------------------------------------------------------------------------
# VIDEO pipeline
# ---------------------------------------------------------------------------

def _run_video(media: Path, out: Path, evidence_id: str):
    obs:      list[Observation] = []
    arts:     list[dict]        = []
    warnings: list[str]         = []

    # --- Stage: ffprobe validation (warns, does not block) ---
    ffprobe_info: dict = {}
    ffprobe_tool = resolve_executable("ffprobe")
    if ffprobe_tool["available"]:
        result = run_tool(
            [ffprobe_tool["path"], "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(media)],
            timeout=60,
        )
        if result["returncode"] == 0:
            try:
                ffprobe_info = json.loads(result["stdout"] or "{}")
            except Exception:
                warnings.append("ffprobe output parse error.")
        else:
            warnings.append(f"ffprobe validation failed: {result['stderr'][:300]}")
    else:
        warnings.append("ffprobe not available; skipping container validation.")

    # --- Stage: frame extraction ---
    frames, extract_warn = _extract_frames_video(media, MAX_FRAMES)
    warnings.extend(extract_warn)

    if not frames:
        # No frames — this is a genuine failure for video
        raise ValueError(f"No frames could be extracted from video '{media.name}'.")

    obs.append(_obs(
        "visual.video_frame_sample",
        f"Extracted {len(frames)} frames from video for visual analysis.",
        {"frames_sampled": len(frames),
         "first_frame_idx": frames[0][0],
         "last_frame_idx":  frames[-1][0],
         "first_ts_s":      frames[0][1],
         "last_ts_s":       frames[-1][1]},
        evidence_id,
        limitations=["Sampled frames represent a subset of the full video."],
    ))

    # --- Stage: face detection setup ---
    cascade = _load_face_cascade()
    if cascade is None:
        warnings.append(
            "Haar cascade XML not found. Face detection skipped. "
            "Install opencv-contrib-python or place haarcascade_frontalface_default.xml "
            "in cv2/data/."
        )

    # --- Per-frame analysis ---
    all_detections: list[dict] = []
    saved_frames:   list[dict] = []
    sharpness_vals: list[float] = []

    for fidx, ts, bgr in frames:
        try:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            sharpness_vals.append(_laplacian_var(gray))

            # Face detection per frame
            faces = _detect_faces(gray, cascade, fidx) if cascade else []
            for fd in faces:
                bbox = fd["bbox"]
                region_metrics = _analyze_face_region(gray, bgr, bbox)
                all_detections.append({**fd, "timestamp_s": ts, **region_metrics})

            # Save frame as PNG artifact
            frame_name = f"frame_{fidx:06d}_{new_id('FRM')}.png"
            frame_path = out / frame_name
            cv2.imwrite(str(frame_path), bgr)
            if frame_path.exists():
                saved_frames.append({
                    "frame_index":   fidx,
                    "timestamp_s":   ts,
                    "path":          str(frame_path),
                    "sha256":        sha256_file(frame_path),
                    "sha512":        sha512_file(frame_path),
                    "size_bytes":    frame_path.stat().st_size,
                    "evidence_id":   evidence_id,
                    "agent_id":      AGENT_ID,
                    "agent_version": VERSION,
                    "created_utc":   utcnow(),
                })
                arts.append({
                    "path":   str(frame_path),
                    "sha256": saved_frames[-1]["sha256"],
                    "type":   "png",
                })
        except Exception as exc:
            warnings.append(f"Frame {fidx} analysis error: {exc}")

    # Frame manifest
    manifest_art = _write_frame_manifest(frames, saved_frames, out, evidence_id)
    arts.append(manifest_art)

    # --- Face detection summary observation ---
    face_rate = len(all_detections) / len(frames) if frames else 0.0
    obs.append(_obs(
        "visual.face_detection",
        (f"Detected {len(all_detections)} face instance(s) across "
         f"{len(frames)} sampled frame(s)."
         if cascade else
         "Face detection was not performed; Haar cascade unavailable."),
        {"frames_examined":    len(frames),
         "faces_detected":     len(all_detections),
         "face_detection_rate": round(face_rate, 4),
         "cascade_available":  cascade is not None},
        evidence_id,
        alt_expl=["occlusion", "extreme pose", "low resolution",
                  "non-human subjects", "mask/glasses"],
        limitations=[
            "Haar-based detection is a screening signal.",
            "Zero detections do not indicate absence of a person.",
        ],
    ))

    # Sharpness across frames
    if sharpness_vals:
        mean_s = float(np.mean(sharpness_vals))
        std_s  = float(np.std(sharpness_vals))
        obs.append(_obs(
            "visual.video_sharpness_profile",
            f"Frame sharpness (Laplacian variance): mean={mean_s:.2f}, std={std_s:.2f} "
            f"across {len(sharpness_vals)} sampled frames.",
            {"mean_sharpness": round(mean_s, 3),
             "std_sharpness":  round(std_s, 3),
             "frame_count":    len(sharpness_vals)},
            evidence_id,
            alt_expl=["motion blur", "focus changes", "transcoding", "scene changes"],
            limitations=["Sharpness variation alone is not indicative of manipulation."],
        ))

    # Face boundary variation across frames
    boundary_scores = [d.get("boundary_face_ratio", 0.0) for d in all_detections
                       if "boundary_face_ratio" in d]
    if len(boundary_scores) >= 4:
        mean_r = float(np.mean(boundary_scores))
        std_r  = float(np.std(boundary_scores))
        cv_r   = std_r / mean_r if mean_r > 0 else 0.0
        obs.append(_obs(
            "visual.face_boundary_variation",
            f"Face-boundary ratio varied across {len(boundary_scores)} detections "
            f"(CV={cv_r:.4f}).",
            {"mean_ratio":   round(mean_r, 4),
             "std_ratio":    round(std_r, 4),
             "cv":           round(cv_r, 4),
             "face_count":   len(boundary_scores)},
            evidence_id,
            supports=["H2", "H5"] if cv_r > 0.5 else [],
            alt_expl=["compression", "resizing", "focus changes", "lighting"],
            limitations=["Coefficient of variation is not calibrated to manipulation probability."],
        ))

    raw_data = {
        "agent":           AGENT_ID,
        "version":         VERSION,
        "media":           media.name,
        "frames_sampled":  len(frames),
        "faces_total":     len(all_detections),
        "sharpness_vals":  [round(v, 2) for v in sharpness_vals],
        "all_detections":  all_detections,
        "warnings":        warnings,
    }
    arts.append(_save_artifact(raw_data, out, "visual_video"))

    return obs, arts, warnings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(media: Path, out: Path, evidence_id: str, media_type: str):
    """
    Run the visual forensics pipeline.
    Returns (observations, artifacts, warnings).
    Raises only on unrecoverable decode/read failure.
    """
    out.mkdir(parents=True, exist_ok=True)

    ext = media.suffix.lower()

    if media_type == "image" or ext in _IMAGE_EXTS:
        return _run_image(media, out, evidence_id)

    elif media_type == "video" or ext in _VIDEO_EXTS:
        return _run_video(media, out, evidence_id)

    else:
        # Unknown modality — attempt image decode first, then raise
        try:
            return _run_image(media, out, evidence_id)
        except Exception:
            raise ValueError(
                f"Unsupported media type '{ext}' for visual forensics. "
                f"Supported: {sorted(_IMAGE_EXTS | _VIDEO_EXTS)}"
            )
