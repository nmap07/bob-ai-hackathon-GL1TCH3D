"""
app/agents/metadata.py
Metadata extraction agent — modality-aware.
IMAGE : Pillow (mandatory) + ExifTool (optional)
VIDEO : ffprobe (mandatory) + ExifTool (optional)
A missing optional tool yields COMPLETED_WITH_WARNINGS, never FAILED.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.schemas import Observation
from app.utils import new_id, sha256_file, sha512_file, utcnow
from app.forensics.tooling import resolve_executable, run_tool

AGENT_ID = "metadata-analysis"
VERSION  = "2.1.0"

# Image extensions handled by Pillow path
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
# Video extensions handled by ffprobe path
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".m2ts", ".3gp"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obs(type_: str, statement: str, measurement: dict, evidence_id: str,
         calibrated: bool = True, limitations: list[str] | None = None) -> Observation:
    return Observation(
        observation_id=new_id("OBS"),
        agent_id=AGENT_ID,
        agent_version=VERSION,
        type=type_,
        statement=statement,
        measurement=measurement,
        basis=[evidence_id],
        calibrated=calibrated,
        limitations=limitations or ["Metadata is descriptive and may reflect post-processing."],
    )


def _save_artifact(data: dict | str | bytes, out: Path, prefix: str) -> dict:
    raw = out / f"{prefix}_{new_id('RAW')}.json"
    if isinstance(data, (dict, list)):
        raw.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    elif isinstance(data, bytes):
        raw.write_bytes(data)
    else:
        raw.write_text(str(data), encoding="utf-8")
    return {"path": str(raw), "sha256": sha256_file(raw), "type": "json"}


# ---------------------------------------------------------------------------
# Image metadata via Pillow
# ---------------------------------------------------------------------------

def _pillow_metadata(media: Path, out: Path, evidence_id: str):
    obs: list[Observation] = []
    arts: list[dict] = []
    warnings: list[str] = []

    try:
        from PIL import Image, ExifTags
        from PIL.ExifTags import TAGS

        with Image.open(str(media)) as img:
            fmt      = img.format or media.suffix.lstrip(".").upper()
            mode     = img.mode
            width, height = img.size
            size_bytes = media.stat().st_size

            facts: dict = {
                "format":     fmt,
                "width":      width,
                "height":     height,
                "color_mode": mode,
                "size_bytes": size_bytes,
                "filename":   media.name,
            }

            # Raw EXIF
            exif_data: dict = {}
            try:
                raw_exif = img._getexif()  # type: ignore[attr-defined]
                if raw_exif:
                    for tag_id, value in raw_exif.items():
                        tag_name = TAGS.get(tag_id, str(tag_id))
                        try:
                            # Serialize IFDRational and other non-JSON types
                            exif_data[tag_name] = str(value) if not isinstance(value, (int, float, str, bool, type(None))) else value
                        except Exception:
                            exif_data[tag_name] = repr(value)
                    facts["exif_software"]     = exif_data.get("Software")
                    facts["exif_datetime"]     = exif_data.get("DateTime")
                    facts["exif_make"]         = exif_data.get("Make")
                    facts["exif_model"]        = exif_data.get("Model")
                    facts["exif_orientation"]  = exif_data.get("Orientation")
                    gps = exif_data.get("GPSInfo")
                    if gps:
                        facts["exif_gps_present"] = True
            except Exception as exc:
                warnings.append(f"EXIF extraction partial: {exc}")

            # XMP via Pillow info dict
            xmp_raw = img.info.get("xmp") or img.info.get("XML:com.adobe.xmp")
            if xmp_raw:
                facts["xmp_present"] = True

            full_meta = {"pillow": facts, "exif": exif_data, "pil_info_keys": list(img.info.keys())}
            arts.append(_save_artifact(full_meta, out, "metadata_image"))

            obs.append(_obs(
                "metadata.image_properties",
                f"Image decoded by Pillow: {fmt} {width}×{height} px, mode={mode}, {size_bytes} bytes.",
                {k: v for k, v in facts.items() if v is not None},
                evidence_id,
            ))

            if exif_data:
                obs.append(_obs(
                    "metadata.exif",
                    f"EXIF metadata present with {len(exif_data)} tag(s).",
                    {"tag_count": len(exif_data), "software": exif_data.get("Software"),
                     "datetime": exif_data.get("DateTime"), "make": exif_data.get("Make"),
                     "model": exif_data.get("Model"), "orientation": exif_data.get("Orientation")},
                    evidence_id,
                    limitations=["EXIF data can be modified; it is descriptive metadata only."],
                ))
            else:
                obs.append(_obs(
                    "metadata.exif_absent",
                    "No EXIF metadata found in image.",
                    {"exif_present": False},
                    evidence_id,
                    limitations=["Absence of EXIF may result from stripping, platform processing, or original absence."],
                ))

    except ImportError:
        warnings.append("Pillow not installed; image metadata extraction unavailable.")
    except Exception as exc:
        warnings.append(f"Pillow metadata extraction failed: {exc}")

    return obs, arts, warnings


# ---------------------------------------------------------------------------
# Optional ExifTool enrichment (image or video)
# ---------------------------------------------------------------------------

def _exiftool_metadata(media: Path, out: Path, evidence_id: str):
    obs: list[Observation] = []
    arts: list[dict] = []
    warnings: list[str] = []

    tool = resolve_executable("exiftool")
    if not tool["available"]:
        warnings.append("ExifTool not installed; detailed EXIF/XMP/IPTC metadata not extracted.")
        return obs, arts, warnings

    result = run_tool([tool["path"], "-j", "-a", "-u", "-g", str(media)], timeout=30)
    arts.append(_save_artifact(
        {"tool": "exiftool", "version": tool["version"], "run": result},
        out, "metadata_exiftool",
    ))

    if result["returncode"] == 0 and result["stdout"].strip():
        try:
            data = json.loads(result["stdout"])
            if isinstance(data, list) and data:
                et = data[0]
                obs.append(_obs(
                    "metadata.exiftool",
                    f"ExifTool extracted {len(et)} metadata fields.",
                    {"field_count": len(et), "tool_version": tool["version"]},
                    evidence_id,
                    limitations=["ExifTool metadata reflects what is embedded in the file; it can be altered."],
                ))
        except json.JSONDecodeError as exc:
            warnings.append(f"ExifTool output parse error: {exc}")
    else:
        warnings.append(f"ExifTool exited {result['returncode']}: {result['stderr'][:500]}")

    return obs, arts, warnings


# ---------------------------------------------------------------------------
# Video metadata via ffprobe
# ---------------------------------------------------------------------------

def _ffprobe_metadata(media: Path, out: Path, evidence_id: str):
    obs: list[Observation] = []
    arts: list[dict] = []
    warnings: list[str] = []

    tool = resolve_executable("ffprobe")
    if not tool["available"]:
        warnings.append("ffprobe not found; video container/stream metadata not extracted.")
        return obs, arts, warnings

    result = run_tool(
        [tool["path"], "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(media)],
        timeout=60,
    )
    arts.append(_save_artifact(
        {"tool": "ffprobe", "version": tool["version"], "run": result},
        out, "metadata_ffprobe",
    ))

    if result["returncode"] != 0:
        warnings.append(f"ffprobe failed (rc={result['returncode']}): {result['stderr'][:500]}")
        return obs, arts, warnings

    try:
        data   = json.loads(result["stdout"] or "{}")
        fmt    = data.get("format", {})
        streams = data.get("streams", [])
        video  = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio  = next((s for s in streams if s.get("codec_type") == "audio"), {})

        facts = {
            "container":         fmt.get("format_name"),
            "duration_seconds":  fmt.get("duration"),
            "format_tags":       fmt.get("tags", {}),
            "video_codec":       video.get("codec_name"),
            "resolution":        [video.get("width"), video.get("height")] if video else None,
            "r_frame_rate":      video.get("r_frame_rate"),
            "avg_frame_rate":    video.get("avg_frame_rate"),
            "audio_codec":       audio.get("codec_name"),
            "audio_sample_rate": audio.get("sample_rate"),
            "audio_channels":    audio.get("channels"),
            "stream_count":      len(streams),
            "encoder": (video.get("tags", {}).get("encoder")
                        or fmt.get("tags", {}).get("encoder")),
        }

        for k, v in facts.items():
            if v is not None:
                obs.append(_obs(
                    f"metadata.{k}",
                    f"{k} observed as {v!r}.",
                    {"value": v},
                    evidence_id,
                ))
    except Exception as exc:
        warnings.append(f"ffprobe output parse error: {exc}")

    return obs, arts, warnings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(media: Path, out: Path, evidence_id: str):
    out.mkdir(parents=True, exist_ok=True)
    obs:      list[Observation] = []
    arts:     list[dict]        = []
    warnings: list[str]         = []

    ext = media.suffix.lower()

    if ext in _IMAGE_EXTS:
        # --- IMAGE PATH ---
        p_obs, p_arts, p_warn = _pillow_metadata(media, out, evidence_id)
        obs.extend(p_obs); arts.extend(p_arts); warnings.extend(p_warn)

        # ExifTool as optional enrichment (never blocks success)
        e_obs, e_arts, e_warn = _exiftool_metadata(media, out, evidence_id)
        obs.extend(e_obs); arts.extend(e_arts); warnings.extend(e_warn)

    elif ext in _VIDEO_EXTS:
        # --- VIDEO PATH ---
        f_obs, f_arts, f_warn = _ffprobe_metadata(media, out, evidence_id)
        obs.extend(f_obs); arts.extend(f_arts); warnings.extend(f_warn)

        # ExifTool as optional enrichment
        e_obs, e_arts, e_warn = _exiftool_metadata(media, out, evidence_id)
        obs.extend(e_obs); arts.extend(e_arts); warnings.extend(e_warn)

    else:
        # Unknown/audio — attempt Pillow, fall back gracefully
        try:
            from PIL import Image
            with Image.open(str(media)):
                p_obs, p_arts, p_warn = _pillow_metadata(media, out, evidence_id)
                obs.extend(p_obs); arts.extend(p_arts); warnings.extend(p_warn)
        except Exception:
            warnings.append(f"Unsupported media type for metadata extraction: {ext}")

    return obs, arts, warnings
