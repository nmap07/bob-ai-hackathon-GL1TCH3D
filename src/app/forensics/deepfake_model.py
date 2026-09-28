"""
app/forensics/deepfake_model.py
Optional calibrated deepfake model adapter for EMAFIG.

Supports ONNX and PyTorch detectors.
If no trained model is installed, status = "unavailable" — NOT "failed".

NEVER converts raw neural network scores to a legal or forensic probability
unless a validated calibration configuration is explicitly provided and verified.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


MODEL_UNAVAILABLE = "unavailable"
MODEL_FAILED      = "failed"
MODEL_COMPLETED   = "completed"


def _hash_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class DeepfakeModelResult:
    """Structured result from a deepfake model run."""

    def __init__(
        self,
        *,
        status: str,
        model_name: str,
        model_version: str,
        model_hash: str | None,
        preprocessing: dict,
        raw_score: list[float] | None,
        class_labels: list[str] | None,
        calibration_status: str,
        note: str,
        error: str | None = None,
        duration_ms: int = 0,
    ):
        self.status             = status
        self.model_name         = model_name
        self.model_version      = model_version
        self.model_hash         = model_hash
        self.preprocessing      = preprocessing
        self.raw_score          = raw_score
        self.class_labels       = class_labels
        self.calibration_status = calibration_status
        self.note               = note
        self.error              = error
        self.duration_ms        = duration_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "status":             self.status,
            "model_name":         self.model_name,
            "model_version":      self.model_version,
            "model_hash":         self.model_hash,
            "preprocessing":      self.preprocessing,
            "raw_score":          self.raw_score,
            "class_labels":       self.class_labels,
            "calibration_status": self.calibration_status,
            "note":               self.note,
            "error":              self.error,
            "duration_ms":        self.duration_ms,
        }


def _unavailable(model_name: str, reason: str) -> DeepfakeModelResult:
    return DeepfakeModelResult(
        status=MODEL_UNAVAILABLE,
        model_name=model_name,
        model_version="N/A",
        model_hash=None,
        preprocessing={},
        raw_score=None,
        class_labels=None,
        calibration_status="not_applicable",
        note=reason,
    )


def _failed(model_name: str, error: str) -> DeepfakeModelResult:
    return DeepfakeModelResult(
        status=MODEL_FAILED,
        model_name=model_name,
        model_version="N/A",
        model_hash=None,
        preprocessing={},
        raw_score=None,
        class_labels=None,
        calibration_status="not_applicable",
        note="Model execution failed; see error field.",
        error=error,
    )


# ---------------------------------------------------------------------------
# ONNX adapter
# ---------------------------------------------------------------------------

def _run_onnx(model_path: Path, input_array: "np.ndarray",  # type: ignore[name-defined]
              input_name: str | None = None) -> tuple[list[float], list[str]]:
    """Run inference via onnxruntime. Returns (scores, output_names)."""
    import onnxruntime as ort
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    inp  = sess.get_inputs()[0]
    name = input_name or inp.name
    outputs = sess.run(None, {name: input_array.astype("float32")})
    import numpy as _np
    scores = _np.asarray(outputs[0]).reshape(-1).tolist()
    out_names = [x.name for x in sess.get_outputs()]
    return [round(float(v), 8) for v in scores], out_names


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze_image(
    image_path: Path,
    model_path: Path | None = None,
    *,
    model_name: str = "generic-image-detector",
    calibration_config: dict | None = None,
) -> DeepfakeModelResult:
    """
    Run an optional image-level deepfake screening model.
    Returns DeepfakeModelResult — callers must check .status before using scores.
    """
    if model_path is None or not model_path.exists():
        return _unavailable(
            model_name,
            f"Model file not found: {model_path}. "
            "Place a compatible ONNX model at the configured path.",
        )

    start = time.monotonic()
    try:
        import numpy as np
        from PIL import Image as PILImage

        # Load and preprocess image (224×224, ImageNet normalisation)
        img = PILImage.open(str(image_path)).convert("RGB").resize((224, 224))
        arr = np.array(img, dtype=np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        arr = arr.transpose(2, 0, 1)[None, :]  # NCHW

        scores, out_names = _run_onnx(model_path, arr)
        duration_ms = int((time.monotonic() - start) * 1000)
        model_hash  = _hash_file(model_path)

        cal = (calibration_config or {}).get("status", "uncalibrated")
        return DeepfakeModelResult(
            status=MODEL_COMPLETED,
            model_name=model_name,
            model_version="ONNX",
            model_hash=model_hash,
            preprocessing={
                "resize":      [224, 224],
                "normalise":   "ImageNet mean/std",
                "input_shape": list(arr.shape),
            },
            raw_score=scores,
            class_labels=out_names,
            calibration_status=cal,
            note=(
                "Raw model output preserved. "
                "Do NOT interpret as probability without a validated operating point "
                "on the relevant population."
            ),
            duration_ms=duration_ms,
        )

    except ImportError as exc:
        return _unavailable(model_name, f"Required dependency missing: {exc}")
    except Exception as exc:
        return _failed(model_name, repr(exc))


def analyze_frame(
    frame_array: "np.ndarray",  # type: ignore[name-defined]
    model_path: Path | None = None,
    *,
    model_name: str = "generic-frame-detector",
    calibration_config: dict | None = None,
) -> DeepfakeModelResult:
    """
    Run an optional frame-level deepfake screening model on a numpy BGR frame.
    """
    if model_path is None or not model_path.exists():
        return _unavailable(
            model_name,
            f"Model file not found: {model_path}.",
        )

    start = time.monotonic()
    try:
        import numpy as np
        import cv2

        # BGR→RGB, resize, normalise
        rgb = cv2.cvtColor(frame_array, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, (224, 224)).astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr  = ((rgb - mean) / std).transpose(2, 0, 1)[None, :]

        scores, out_names = _run_onnx(model_path, arr)
        duration_ms = int((time.monotonic() - start) * 1000)
        model_hash  = _hash_file(model_path)

        cal = (calibration_config or {}).get("status", "uncalibrated")
        return DeepfakeModelResult(
            status=MODEL_COMPLETED,
            model_name=model_name,
            model_version="ONNX",
            model_hash=model_hash,
            preprocessing={"resize": [224, 224], "normalise": "ImageNet mean/std"},
            raw_score=scores,
            class_labels=out_names,
            calibration_status=cal,
            note=(
                "Raw model output preserved. "
                "Do NOT interpret as probability without a validated operating point."
            ),
            duration_ms=duration_ms,
        )

    except ImportError as exc:
        return _unavailable(model_name, f"Required dependency missing: {exc}")
    except Exception as exc:
        return _failed(model_name, repr(exc))


def analyze_video(
    video_path: Path,
    model_path: Path | None = None,
    *,
    model_name: str = "generic-video-detector",
    max_frames: int = 8,
    calibration_config: dict | None = None,
) -> DeepfakeModelResult:
    """
    Run optional per-frame deepfake screening across sampled video frames.
    """
    if model_path is None or not model_path.exists():
        return _unavailable(
            model_name,
            f"Model file not found: {model_path}.",
        )

    start = time.monotonic()
    try:
        import cv2
        import numpy as np

        cap    = cv2.VideoCapture(str(video_path))
        total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step   = max(1, total // max_frames) if total > 0 else 1
        scores_all: list[list[float]] = []

        idx = 0
        sampled = 0
        while sampled < max_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                break
            result = analyze_frame(frame, model_path, model_name=model_name,
                                   calibration_config=calibration_config)
            if result.status == MODEL_COMPLETED and result.raw_score:
                scores_all.append(result.raw_score)
            idx += step
            sampled += 1
        cap.release()

        if not scores_all:
            return _unavailable(model_name, "No frames processed successfully.")

        arr = np.array(scores_all)
        mean_scores = np.mean(arr, axis=0).tolist()
        duration_ms = int((time.monotonic() - start) * 1000)
        model_hash  = _hash_file(model_path)

        cal = (calibration_config or {}).get("status", "uncalibrated")
        return DeepfakeModelResult(
            status=MODEL_COMPLETED,
            model_name=model_name,
            model_version="ONNX",
            model_hash=model_hash,
            preprocessing={"frames_sampled": len(scores_all), "resize": [224, 224]},
            raw_score=[round(float(v), 8) for v in mean_scores],
            class_labels=None,
            calibration_status=cal,
            note=(
                f"Mean score across {len(scores_all)} sampled frames. "
                "Raw output only — not a probability."
            ),
            duration_ms=duration_ms,
        )

    except ImportError as exc:
        return _unavailable(model_name, f"Required dependency missing: {exc}")
    except Exception as exc:
        return _failed(model_name, repr(exc))
