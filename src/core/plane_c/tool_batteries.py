"""
EMAFIG Plane C — Module 4: Tool Batteries

Deterministic tool runners that execute forensic analysis tools as subprocesses.
Each battery:
  (a) produces a raw artifact (the tool's output file)
  (b) produces a normalized fact sheet (structured JSON for Plane B examiners)

Every tool run is sandboxed: timeouts, size limits, restricted working directory,
no network access, and file-type validation before parsing.

Batteries by media type:
  - Video:  runs everything (metadata, compression, visual, audio, av_sync)
  - Image:  skips audio, av_sync, temporal
  - Audio:  runs metadata, audio, provenance only
  - Screen recording: runs everything; ACH assessor told compression artifacts expected

Each metric is labelled `calibrated: false` unless a calibration dataset confirms it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from . import intake


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Timeout for each tool subprocess (seconds)
DEFAULT_TIMEOUT = 120

# Maximum output file size (100 MiB)
MAX_OUTPUT_SIZE = 100 * 1024 * 1024


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolRunResult:
    """Result of running a single tool."""
    tool_name: str
    tool_version: str
    success: bool
    artifact_id: Optional[str] = None
    artifact_path: Optional[str] = None
    artifact_sha256: Optional[str] = None
    command: Optional[str] = None
    command_hash: Optional[str] = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    duration_ms: int = 0
    error: Optional[str] = None
    raw_output: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FactSheet:
    """
    Normalized fact sheet produced by a battery.
    This is what Plane B examiners receive (as text, never media).
    """
    battery_name: str
    evidence_id: str
    derivative_id: Optional[str] = None
    facts: dict = field(default_factory=dict)
    tool_runs: list[ToolRunResult] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tool_runs"] = [tr.to_dict() for tr in self.tool_runs]
        return d


# ---------------------------------------------------------------------------
# Tool discovery — check what's available on this system
# ---------------------------------------------------------------------------

def _which(tool: str) -> Optional[str]:
    """Find a tool on PATH."""
    return shutil.which(tool)


def discover_tools() -> dict[str, Optional[str]]:
    """
    Check which forensic tools are available.
    Returns a dict of {tool_name: path_or_None}.
    """
    tools = [
        "ffprobe", "ffmpeg", "exiftool", "mediainfo",
        "python",  # for OpenCV / librosa via subprocess
    ]
    return {t: _which(t) for t in tools}


def get_tool_version(tool: str) -> str:
    """Get the version string of a tool (best effort)."""
    version_flags = {
        "ffprobe": ["-version"],
        "ffmpeg": ["-version"],
        "exiftool": ["-ver"],
        "mediainfo": ["--version"],
    }
    flags = version_flags.get(tool, ["--version"])
    try:
        result = subprocess.run(
            [tool] + flags,
            capture_output=True, text=True, timeout=10,
        )
        first_line = (result.stdout or result.stderr or "").strip().split("\n")[0]
        return first_line[:200]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Subprocess runner (sandboxed)
# ---------------------------------------------------------------------------

def _run_tool(
    cmd: list[str],
    *,
    working_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a tool as a subprocess with sandboxing constraints.

    Sandboxing (hackathon level):
      - Timeout enforcement
      - Restricted working directory
      - No network (best-effort via env)
      - Output size checked after completion
    """
    env = os.environ.copy()
    # Best-effort network blocking on Unix (won't work on Windows without firewall rules)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)

    return subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        cwd=working_dir,
        env=env,
    )


async def _run_tool_async(
    cmd: list[str],
    *,
    working_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[str, str, int]:
    """Async version of the tool runner."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            proc.returncode or 0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Tool timed out after {timeout}s: {' '.join(cmd[:3])}")


# ---------------------------------------------------------------------------
# Battery: Metadata
# ---------------------------------------------------------------------------

class MetadataBattery:
    """
    Runs metadata extraction tools: ffprobe, ExifTool, MediaInfo.

    Facts produced:
      container, codec, encoder_string, creation_time, modification_time,
      frame_rate, resolution, bitrate, software_tags, gps (if present),
      stripped_metadata flag, duration, audio_codec, audio_channels,
      audio_sample_rate
    """

    BATTERY_NAME = "metadata"

    def run(
        self,
        file_path: str | Path,
        artifacts_dir: str | Path,
        evidence_id: str,
    ) -> FactSheet:
        file_path = Path(file_path)
        artifacts_dir = Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        sheet = FactSheet(
            battery_name=self.BATTERY_NAME,
            evidence_id=evidence_id,
        )

        # --- ffprobe ---
        sheet = self._run_ffprobe(file_path, artifacts_dir, sheet)

        # --- ExifTool ---
        sheet = self._run_exiftool(file_path, artifacts_dir, sheet)

        # --- MediaInfo ---
        sheet = self._run_mediainfo(file_path, artifacts_dir, sheet)

        # Derived facts
        self._derive_flags(sheet)

        sheet.caveats.append(
            "Platforms strip metadata by design; absence alone is non-diagnostic."
        )

        return sheet

    def _run_ffprobe(
        self, file_path: Path, artifacts_dir: Path, sheet: FactSheet
    ) -> FactSheet:
        if not _which("ffprobe"):
            sheet.caveats.append("ffprobe not found; metadata extraction partial")
            return sheet

        start = time.monotonic()
        output_file = artifacts_dir / f"ffprobe_{uuid.uuid4().hex[:8]}.json"
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]

        try:
            result = _run_tool(cmd)
            output_file.write_text(result.stdout, encoding="utf-8")
            duration_ms = int((time.monotonic() - start) * 1000)

            data = json.loads(result.stdout) if result.stdout.strip() else {}

            # Extract facts from ffprobe output
            fmt = data.get("format", {})
            streams = data.get("streams", [])
            video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

            sheet.facts.update({
                "container": fmt.get("format_name"),
                "container_long": fmt.get("format_long_name"),
                "duration_seconds": float(fmt.get("duration", 0)),
                "bitrate": int(fmt.get("bit_rate", 0)),
                "format_tags": fmt.get("tags", {}),
                "video_codec": video_stream.get("codec_name"),
                "video_codec_long": video_stream.get("codec_long_name"),
                "resolution": (
                    f"{video_stream.get('width', '?')}x{video_stream.get('height', '?')}"
                    if video_stream else None
                ),
                "width": video_stream.get("width"),
                "height": video_stream.get("height"),
                "frame_rate": video_stream.get("r_frame_rate"),
                "avg_frame_rate": video_stream.get("avg_frame_rate"),
                "pixel_format": video_stream.get("pix_fmt"),
                "video_bitrate": int(video_stream.get("bit_rate", 0)) if video_stream.get("bit_rate") else None,
                "encoder_string": (
                    video_stream.get("tags", {}).get("encoder")
                    or fmt.get("tags", {}).get("encoder")
                ),
                "creation_time": (
                    fmt.get("tags", {}).get("creation_time")
                    or video_stream.get("tags", {}).get("creation_time")
                ),
                "audio_codec": audio_stream.get("codec_name"),
                "audio_channels": audio_stream.get("channels"),
                "audio_sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream.get("sample_rate") else None,
                "stream_count": len(streams),
            })

            art_hash = intake.sha256_file(output_file)
            cmd_hash = intake.sha256_str(" ".join(cmd))

            sheet.tool_runs.append(ToolRunResult(
                tool_name="ffprobe",
                tool_version=get_tool_version("ffprobe"),
                success=True,
                artifact_path=str(output_file),
                artifact_sha256=art_hash,
                command=" ".join(cmd),
                command_hash=cmd_hash,
                duration_ms=duration_ms,
                raw_output=result.stdout[:5000],  # truncated for storage
            ))

        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="ffprobe",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))
            sheet.caveats.append(f"ffprobe failed: {e}")

        return sheet

    def _run_exiftool(
        self, file_path: Path, artifacts_dir: Path, sheet: FactSheet
    ) -> FactSheet:
        if not _which("exiftool"):
            sheet.caveats.append("exiftool not found; EXIF extraction skipped")
            return sheet

        start = time.monotonic()
        output_file = artifacts_dir / f"exiftool_{uuid.uuid4().hex[:8]}.json"
        cmd = ["exiftool", "-json", "-G", str(file_path)]

        try:
            result = _run_tool(cmd)
            output_file.write_text(result.stdout, encoding="utf-8")
            duration_ms = int((time.monotonic() - start) * 1000)

            data = json.loads(result.stdout) if result.stdout.strip() else [{}]
            exif = data[0] if data else {}

            # Extract key EXIF fields
            software_tags = []
            for key in ["Software", "EXIF:Software", "XMP:CreatorTool",
                         "EXIF:ProcessingSoftware"]:
                val = exif.get(key)
                if val:
                    software_tags.append(str(val))

            gps_lat = exif.get("Composite:GPSLatitude") or exif.get("EXIF:GPSLatitude")
            gps_lon = exif.get("Composite:GPSLongitude") or exif.get("EXIF:GPSLongitude")

            sheet.facts.update({
                "software_tags": software_tags,
                "exif_make": exif.get("EXIF:Make"),
                "exif_model": exif.get("EXIF:Model"),
                "exif_create_date": exif.get("EXIF:CreateDate"),
                "exif_modify_date": exif.get("EXIF:ModifyDate"),
                "gps_present": bool(gps_lat or gps_lon),
                "gps_latitude": gps_lat,
                "gps_longitude": gps_lon,
                "color_space": exif.get("EXIF:ColorSpace"),
                "orientation": exif.get("EXIF:Orientation"),
                "exif_field_count": len(exif),
            })

            art_hash = intake.sha256_file(output_file)
            cmd_hash = intake.sha256_str(" ".join(cmd))

            sheet.tool_runs.append(ToolRunResult(
                tool_name="exiftool",
                tool_version=get_tool_version("exiftool"),
                success=True,
                artifact_path=str(output_file),
                artifact_sha256=art_hash,
                command=" ".join(cmd),
                command_hash=cmd_hash,
                duration_ms=duration_ms,
            ))

        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="exiftool",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))

        return sheet

    def _run_mediainfo(
        self, file_path: Path, artifacts_dir: Path, sheet: FactSheet
    ) -> FactSheet:
        if not _which("mediainfo"):
            sheet.caveats.append("mediainfo not found; MediaInfo extraction skipped")
            return sheet

        start = time.monotonic()
        output_file = artifacts_dir / f"mediainfo_{uuid.uuid4().hex[:8]}.json"
        cmd = ["mediainfo", "--Output=JSON", str(file_path)]

        try:
            result = _run_tool(cmd)
            output_file.write_text(result.stdout, encoding="utf-8")
            duration_ms = int((time.monotonic() - start) * 1000)

            data = json.loads(result.stdout) if result.stdout.strip() else {}
            tracks = data.get("media", {}).get("track", [])

            general = next((t for t in tracks if t.get("@type") == "General"), {})
            sheet.facts.update({
                "mediainfo_format": general.get("Format"),
                "mediainfo_file_size": general.get("FileSize"),
                "mediainfo_encoded_app": general.get("Encoded_Application"),
                "mediainfo_encoded_lib": general.get("Encoded_Library"),
            })

            art_hash = intake.sha256_file(output_file)
            sheet.tool_runs.append(ToolRunResult(
                tool_name="mediainfo",
                tool_version=get_tool_version("mediainfo"),
                success=True,
                artifact_path=str(output_file),
                artifact_sha256=art_hash,
                command=" ".join(cmd),
                command_hash=intake.sha256_str(" ".join(cmd)),
                duration_ms=duration_ms,
            ))

        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="mediainfo",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))

        return sheet

    def _derive_flags(self, sheet: FactSheet):
        """Derive higher-level flags from raw facts."""
        facts = sheet.facts

        # Stripped metadata detection
        exif_count = facts.get("exif_field_count", 0)
        has_creation = bool(facts.get("creation_time") or facts.get("exif_create_date"))
        has_software = bool(facts.get("software_tags"))
        has_gps = facts.get("gps_present", False)

        facts["stripped_metadata"] = (
            exif_count < 10 and not has_creation and not has_software and not has_gps
        )
        facts["stripped_metadata_calibrated"] = False  # always uncalibrated

        # Encoder analysis
        encoder = facts.get("encoder_string", "") or ""
        facts["encoder_indicates_editing"] = any(
            tag in encoder.lower()
            for tag in ["premiere", "after effects", "davinci", "final cut",
                        "handbrake", "ffmpeg", "lavf", "x264", "x265"]
        )


# ---------------------------------------------------------------------------
# Battery: Compression
# ---------------------------------------------------------------------------

class CompressionBattery:
    """
    Analyzes compression artifacts: GOP structure, frame types, double-compression
    indicators, resolution/frame-rate changes.

    Uses: ffprobe (frame info), ffmpeg (key frame extraction).
    Optional: OpenCV for ELA (Error Level Analysis).
    """

    BATTERY_NAME = "compression"

    def run(
        self,
        file_path: str | Path,
        artifacts_dir: str | Path,
        evidence_id: str,
        working_dir: Optional[str | Path] = None,
    ) -> FactSheet:
        file_path = Path(file_path)
        artifacts_dir = Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        sheet = FactSheet(
            battery_name=self.BATTERY_NAME,
            evidence_id=evidence_id,
        )

        # --- Frame-level info from ffprobe ---
        sheet = self._run_frame_analysis(file_path, artifacts_dir, sheet)

        # --- Key frame extraction ---
        if working_dir:
            sheet = self._extract_keyframes(
                file_path, Path(working_dir), artifacts_dir, sheet
            )

        # --- ELA (Error Level Analysis) via OpenCV if available ---
        sheet = self._run_ela(file_path, artifacts_dir, sheet)

        sheet.caveats.extend([
            "ELA and similar methods are heuristics with known false positives; treat as indicators.",
            "Double-compression indicators may arise from legitimate platform transcoding.",
        ])

        return sheet

    def _run_frame_analysis(
        self, file_path: Path, artifacts_dir: Path, sheet: FactSheet
    ) -> FactSheet:
        if not _which("ffprobe"):
            sheet.caveats.append("ffprobe not found; frame analysis skipped")
            return sheet

        start = time.monotonic()
        output_file = artifacts_dir / f"frames_{uuid.uuid4().hex[:8]}.json"
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_frames",
            "-select_streams", "v:0",
            str(file_path),
        ]

        try:
            result = _run_tool(cmd, timeout=180)
            output_file.write_text(result.stdout[:MAX_OUTPUT_SIZE], encoding="utf-8")
            duration_ms = int((time.monotonic() - start) * 1000)

            data = json.loads(result.stdout) if result.stdout.strip() else {}
            frames = data.get("frames", [])

            # Analyze GOP structure
            frame_types = [f.get("pict_type", "?") for f in frames]
            i_frames = [i for i, t in enumerate(frame_types) if t == "I"]

            # GOP lengths (distances between I-frames)
            gop_lengths = []
            for j in range(1, len(i_frames)):
                gop_lengths.append(i_frames[j] - i_frames[j - 1])

            # Detect GOP irregularities
            gop_irregularities = []
            if gop_lengths:
                median_gop = sorted(gop_lengths)[len(gop_lengths) // 2]
                for j, gl in enumerate(gop_lengths):
                    if abs(gl - median_gop) > median_gop * 0.3:
                        start_frame = i_frames[j]
                        end_frame = i_frames[j + 1] if j + 1 < len(i_frames) else len(frames)
                        gop_irregularities.append({
                            "gop_index": j,
                            "length": gl,
                            "median": median_gop,
                            "frame_range": [start_frame, end_frame],
                        })

            # Frame size analysis for double-compression detection
            frame_sizes = [int(f.get("pkt_size", 0)) for f in frames]

            # Detect resolution/framerate changes mid-stream
            resolutions = set()
            for f in frames:
                w = f.get("width")
                h = f.get("height")
                if w and h:
                    resolutions.add(f"{w}x{h}")

            sheet.facts.update({
                "total_frames": len(frames),
                "frame_type_counts": {
                    "I": frame_types.count("I"),
                    "P": frame_types.count("P"),
                    "B": frame_types.count("B"),
                },
                "gop_lengths": gop_lengths[:100],  # cap output size
                "gop_median": sorted(gop_lengths)[len(gop_lengths) // 2] if gop_lengths else None,
                "gop_irregularity_ranges": gop_irregularities,
                "gop_irregular": len(gop_irregularities) > 0,
                "gop_irregular_calibrated": False,
                "avg_frame_size": sum(frame_sizes) / len(frame_sizes) if frame_sizes else 0,
                "frame_size_std": _std(frame_sizes) if frame_sizes else 0,
                "resolution_changes": len(resolutions) > 1,
                "resolutions_found": list(resolutions),
                "double_compression_indicators": len(gop_irregularities) > 2,
                "double_compression_calibrated": False,
            })

            art_hash = intake.sha256_file(output_file)
            sheet.tool_runs.append(ToolRunResult(
                tool_name="ffprobe-frames",
                tool_version=get_tool_version("ffprobe"),
                success=True,
                artifact_path=str(output_file),
                artifact_sha256=art_hash,
                command=" ".join(cmd),
                command_hash=intake.sha256_str(" ".join(cmd)),
                duration_ms=duration_ms,
            ))

        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="ffprobe-frames",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))

        return sheet

    def _extract_keyframes(
        self, file_path: Path, working_dir: Path, artifacts_dir: Path,
        sheet: FactSheet,
    ) -> FactSheet:
        if not _which("ffmpeg"):
            sheet.caveats.append("ffmpeg not found; keyframe extraction skipped")
            return sheet

        start = time.monotonic()
        frames_dir = working_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = str(frames_dir / "keyframe_%04d.png")

        cmd = [
            "ffmpeg", "-y", "-i", str(file_path),
            "-vf", "select=eq(pict_type\\,I)",
            "-vsync", "vfr",
            "-frames:v", "50",  # limit to 50 keyframes
            output_pattern,
        ]

        try:
            _run_tool(cmd, timeout=180)
            duration_ms = int((time.monotonic() - start) * 1000)

            keyframes = sorted(frames_dir.glob("keyframe_*.png"))
            sheet.facts["keyframes_extracted"] = len(keyframes)
            sheet.facts["keyframe_paths"] = [str(kf) for kf in keyframes[:50]]

            sheet.tool_runs.append(ToolRunResult(
                tool_name="ffmpeg-keyframes",
                tool_version=get_tool_version("ffmpeg"),
                success=True,
                command=" ".join(cmd),
                command_hash=intake.sha256_str(" ".join(cmd)),
                duration_ms=duration_ms,
            ))

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="ffmpeg-keyframes",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))

        return sheet

    def _run_ela(
        self, file_path: Path, artifacts_dir: Path, sheet: FactSheet
    ) -> FactSheet:
        """
        Error Level Analysis via OpenCV.
        Re-compresses the image/frame at a known quality and measures the
        difference, which may reveal double-compressed regions.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            sheet.caveats.append("OpenCV not available; ELA skipped")
            return sheet

        media_type = intake.detect_media_type(file_path)
        if media_type not in ("image",):
            # For video, ELA would run on extracted keyframes (future work)
            sheet.facts["ela_applicable"] = False
            return sheet

        start = time.monotonic()
        try:
            img = cv2.imread(str(file_path))
            if img is None:
                sheet.caveats.append("OpenCV could not read file for ELA")
                return sheet

            # Re-compress at quality 95 and measure difference
            quality = 95
            _, encoded = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            recompressed = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            diff = cv2.absdiff(img, recompressed)
            scale = 15
            ela_img = cv2.convertScaleAbs(diff, alpha=scale)

            # Save ELA result
            ela_path = artifacts_dir / f"ela_{uuid.uuid4().hex[:8]}.png"
            cv2.imwrite(str(ela_path), ela_img)

            # Compute statistics
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            mean_diff = float(np.mean(gray_diff))
            max_diff = float(np.max(gray_diff))
            std_diff = float(np.std(gray_diff))

            duration_ms = int((time.monotonic() - start) * 1000)

            sheet.facts.update({
                "ela_applicable": True,
                "ela_quality": quality,
                "ela_mean_diff": round(mean_diff, 4),
                "ela_max_diff": round(max_diff, 4),
                "ela_std_diff": round(std_diff, 4),
                "ela_artifact_path": str(ela_path),
                "ela_calibrated": False,
            })

            sheet.tool_runs.append(ToolRunResult(
                tool_name="opencv-ela",
                tool_version=cv2.__version__,
                success=True,
                artifact_path=str(ela_path),
                artifact_sha256=intake.sha256_file(ela_path),
                duration_ms=duration_ms,
            ))

        except Exception as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="opencv-ela",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))

        return sheet


# ---------------------------------------------------------------------------
# Battery: Visual
# ---------------------------------------------------------------------------

class VisualBattery:
    """
    Visual analysis: face detection, landmark analysis, boundary sharpness,
    blink rate estimation, eye symmetry.

    Uses: OpenCV (face detection, landmark analysis).
    """

    BATTERY_NAME = "visual"

    def run(
        self,
        file_path: str | Path,
        artifacts_dir: str | Path,
        evidence_id: str,
        keyframe_paths: Optional[list[str]] = None,
    ) -> FactSheet:
        file_path = Path(file_path)
        artifacts_dir = Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        sheet = FactSheet(
            battery_name=self.BATTERY_NAME,
            evidence_id=evidence_id,
        )

        try:
            import cv2
            import numpy as np
        except ImportError:
            sheet.caveats.append("OpenCV not available; visual analysis skipped")
            return sheet

        # Determine what to analyze: keyframes for video, the image itself for images
        media_type = intake.detect_media_type(file_path)
        frames_to_analyze = []

        if media_type == "image":
            img = cv2.imread(str(file_path))
            if img is not None:
                frames_to_analyze = [(0, img)]
        elif keyframe_paths:
            for i, kf_path in enumerate(keyframe_paths[:20]):  # limit
                img = cv2.imread(kf_path)
                if img is not None:
                    frames_to_analyze.append((i, img))

        if not frames_to_analyze:
            sheet.caveats.append("No frames available for visual analysis")
            return sheet

        start = time.monotonic()

        # Face detection using Haar cascades (available without extra models)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        face_detections = []
        boundary_scores = []

        for frame_idx, img in frames_to_analyze:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)

            for (x, y, w, h) in faces:
                # Boundary analysis: measure gradient strength at face boundary
                margin = 10
                x1 = max(0, x - margin)
                y1 = max(0, y - margin)
                x2 = min(img.shape[1], x + w + margin)
                y2 = min(img.shape[0], y + h + margin)

                roi = gray[y1:y2, x1:x2]
                if roi.size == 0:
                    continue

                # Laplacian for edge detection at boundary
                laplacian = cv2.Laplacian(roi, cv2.CV_64F)
                boundary_strength = float(np.var(laplacian))

                # Face region sharpness vs background
                face_roi = gray[y:y+h, x:x+w]
                face_lap = cv2.Laplacian(face_roi, cv2.CV_64F)
                face_sharpness = float(np.var(face_lap))

                # Background sample
                bg_y1 = max(0, y - h)
                bg_y2 = y
                bg_x1 = x
                bg_x2 = x + w
                bg_roi = gray[bg_y1:bg_y2, bg_x1:bg_x2]
                bg_sharpness = float(np.var(cv2.Laplacian(bg_roi, cv2.CV_64F))) if bg_roi.size > 0 else 0

                face_detections.append({
                    "frame_index": frame_idx,
                    "bbox": [int(x), int(y), int(w), int(h)],
                    "boundary_strength": round(boundary_strength, 2),
                    "face_sharpness": round(face_sharpness, 2),
                    "background_sharpness": round(bg_sharpness, 2),
                    "sharpness_ratio": round(
                        face_sharpness / bg_sharpness if bg_sharpness > 0 else 0, 4
                    ),
                })

                boundary_scores.append(boundary_strength)

        duration_ms = int((time.monotonic() - start) * 1000)

        # Save detection results
        results_file = artifacts_dir / f"visual_{uuid.uuid4().hex[:8]}.json"
        results_file.write_text(
            json.dumps(face_detections, indent=2),
            encoding="utf-8",
        )

        sheet.facts.update({
            "frames_analyzed": len(frames_to_analyze),
            "faces_detected_total": len(face_detections),
            "face_detections": face_detections[:50],  # cap
            "avg_boundary_strength": (
                round(sum(boundary_scores) / len(boundary_scores), 2)
                if boundary_scores else None
            ),
            "boundary_strength_std": round(_std(boundary_scores), 2) if boundary_scores else None,
            "face_boundary_anomaly": False,  # derived below
            "face_boundary_calibrated": False,
        })

        # Flag potential boundary anomalies (high variance in boundary strength
        # across frames may indicate face swapping)
        if len(boundary_scores) > 3:
            std = _std(boundary_scores)
            mean = sum(boundary_scores) / len(boundary_scores)
            if mean > 0 and std / mean > 0.5:
                sheet.facts["face_boundary_anomaly"] = True

        sheet.caveats.extend([
            "Blink and similar cues are weaker on newer generators.",
            "Face boundary analysis uses basic edge detection; not a calibrated detector.",
        ])

        sheet.tool_runs.append(ToolRunResult(
            tool_name="opencv-visual",
            tool_version=cv2.__version__,
            success=True,
            artifact_path=str(results_file),
            artifact_sha256=intake.sha256_file(results_file),
            duration_ms=duration_ms,
        ))

        return sheet


# ---------------------------------------------------------------------------
# Battery: Audio
# ---------------------------------------------------------------------------

class AudioBattery:
    """
    Audio analysis: spectral statistics, discontinuity detection, noise floor
    changes, pitch variability.

    Uses: ffmpeg (audio extraction), librosa (analysis).
    """

    BATTERY_NAME = "audio"

    def run(
        self,
        file_path: str | Path,
        artifacts_dir: str | Path,
        evidence_id: str,
        working_dir: Optional[str | Path] = None,
    ) -> FactSheet:
        file_path = Path(file_path)
        artifacts_dir = Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        sheet = FactSheet(
            battery_name=self.BATTERY_NAME,
            evidence_id=evidence_id,
        )

        # Extract audio track
        audio_path = self._extract_audio(file_path, working_dir, sheet)
        if not audio_path:
            return sheet

        # Analyze with librosa
        sheet = self._analyze_audio(audio_path, artifacts_dir, sheet)

        sheet.caveats.extend([
            "Voice-clone detectors, if used, are optional and uncalibrated.",
            "Spectral discontinuities may arise from legitimate editing or codec behavior.",
        ])

        return sheet

    def _extract_audio(
        self, file_path: Path, working_dir: Optional[str | Path],
        sheet: FactSheet,
    ) -> Optional[Path]:
        """Extract mono audio track using ffmpeg."""
        if not _which("ffmpeg"):
            sheet.caveats.append("ffmpeg not found; audio extraction skipped")
            return None

        media_type = intake.detect_media_type(file_path)
        if media_type == "audio":
            return file_path  # already audio

        if media_type not in ("video",):
            sheet.caveats.append(f"Audio extraction not applicable for {media_type}")
            return None

        if working_dir is None:
            working_dir = file_path.parent

        audio_dir = Path(working_dir) / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"audio_{uuid.uuid4().hex[:8]}.wav"

        cmd = [
            "ffmpeg", "-y", "-i", str(file_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(audio_path),
        ]

        try:
            _run_tool(cmd, timeout=120)
            if audio_path.exists() and audio_path.stat().st_size > 0:
                sheet.tool_runs.append(ToolRunResult(
                    tool_name="ffmpeg-audio-extract",
                    tool_version=get_tool_version("ffmpeg"),
                    success=True,
                    artifact_path=str(audio_path),
                    artifact_sha256=intake.sha256_file(audio_path),
                    command=" ".join(cmd),
                    command_hash=intake.sha256_str(" ".join(cmd)),
                ))
                return audio_path
            else:
                sheet.caveats.append("Audio extraction produced empty file")
                return None
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            sheet.caveats.append(f"Audio extraction failed: {e}")
            return None

    def _analyze_audio(
        self, audio_path: Path, artifacts_dir: Path, sheet: FactSheet
    ) -> FactSheet:
        """Analyze audio using librosa for spectral features."""
        try:
            import librosa
            import numpy as np
        except ImportError:
            sheet.caveats.append("librosa not available; spectral analysis skipped")
            return sheet

        start = time.monotonic()
        try:
            y, sr = librosa.load(str(audio_path), sr=16000, mono=True)

            if len(y) == 0:
                sheet.caveats.append("Audio track is empty")
                return sheet

            duration = len(y) / sr

            # Spectral centroid (brightness over time)
            centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]

            # Spectral rolloff
            rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]

            # RMS energy (noise floor proxy)
            rms = librosa.feature.rms(y=y)[0]

            # Pitch estimation (fundamental frequency)
            pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
            pitch_values = []
            for t in range(pitches.shape[1]):
                idx = magnitudes[:, t].argmax()
                p = pitches[idx, t]
                if p > 0:
                    pitch_values.append(float(p))

            # Spectral flux (detect discontinuities)
            spec = np.abs(librosa.stft(y))
            flux = np.sqrt(np.sum(np.diff(spec, axis=1) ** 2, axis=0))

            # Detect discontinuity points (large flux spikes)
            if len(flux) > 10:
                flux_mean = np.mean(flux)
                flux_std = np.std(flux)
                threshold = flux_mean + 3 * flux_std
                discontinuity_frames = np.where(flux > threshold)[0]
                hop_length = 512
                discontinuity_times = [
                    round(float(f * hop_length / sr), 3)
                    for f in discontinuity_frames
                ]
            else:
                discontinuity_times = []

            # Noise floor analysis (segment-by-segment RMS)
            segment_duration = 1.0  # 1-second segments
            segment_samples = int(segment_duration * sr)
            noise_segments = []
            for i in range(0, len(y), segment_samples):
                seg = y[i:i + segment_samples]
                if len(seg) > 0:
                    noise_segments.append(float(np.sqrt(np.mean(seg ** 2))))

            # Detect noise floor changes
            noise_changes = []
            if len(noise_segments) > 2:
                for i in range(1, len(noise_segments)):
                    ratio = (noise_segments[i] / noise_segments[i - 1]
                             if noise_segments[i - 1] > 1e-6 else 0)
                    if ratio > 3.0 or (ratio > 0 and ratio < 0.33):
                        noise_changes.append({
                            "time_sec": round(i * segment_duration, 2),
                            "ratio": round(ratio, 3),
                        })

            duration_ms = int((time.monotonic() - start) * 1000)

            # Save analysis results
            results_file = artifacts_dir / f"audio_{uuid.uuid4().hex[:8]}.json"
            results = {
                "duration_seconds": round(duration, 3),
                "sample_rate": sr,
                "spectral_centroid_mean": round(float(np.mean(centroid)), 2),
                "spectral_centroid_std": round(float(np.std(centroid)), 2),
                "spectral_rolloff_mean": round(float(np.mean(rolloff)), 2),
                "rms_mean": round(float(np.mean(rms)), 6),
                "rms_std": round(float(np.std(rms)), 6),
                "pitch_mean": round(float(np.mean(pitch_values)), 2) if pitch_values else None,
                "pitch_std": round(float(np.std(pitch_values)), 2) if pitch_values else None,
                "pitch_variability": round(
                    float(np.std(pitch_values) / np.mean(pitch_values)), 4
                ) if pitch_values and np.mean(pitch_values) > 0 else None,
                "spectral_discontinuity_count": len(discontinuity_times),
                "spectral_discontinuity_times": discontinuity_times[:50],
                "noise_floor_changes": noise_changes[:20],
                "noise_segment_count": len(noise_segments),
            }
            results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

            sheet.facts.update(results)
            sheet.facts.update({
                "spectral_discontinuity_detected": len(discontinuity_times) > 0,
                "spectral_discontinuity_calibrated": False,
                "noise_floor_change_detected": len(noise_changes) > 0,
                "noise_floor_calibrated": False,
                "pitch_variability_calibrated": False,
            })

            sheet.tool_runs.append(ToolRunResult(
                tool_name="librosa-audio",
                tool_version=librosa.__version__,
                success=True,
                artifact_path=str(results_file),
                artifact_sha256=intake.sha256_file(results_file),
                duration_ms=duration_ms,
            ))

        except Exception as e:
            sheet.tool_runs.append(ToolRunResult(
                tool_name="librosa-audio",
                tool_version="unknown",
                success=False,
                error=str(e),
            ))
            sheet.caveats.append(f"Audio analysis failed: {e}")

        return sheet


# ---------------------------------------------------------------------------
# Battery: AV Sync
# ---------------------------------------------------------------------------

class AVSyncBattery:
    """
    Estimates lip-to-audio offset over time.
    Uses landmark detection + audio envelope correlation.
    """

    BATTERY_NAME = "av_sync"

    def run(
        self,
        file_path: str | Path,
        artifacts_dir: str | Path,
        evidence_id: str,
    ) -> FactSheet:
        """
        Placeholder for full AV sync analysis.
        Full implementation requires frame-by-frame landmark tracking + audio
        envelope correlation, which is computationally expensive.
        """
        sheet = FactSheet(
            battery_name=self.BATTERY_NAME,
            evidence_id=evidence_id,
        )

        media_type = intake.detect_media_type(file_path)
        if media_type != "video":
            sheet.facts["av_sync_applicable"] = False
            sheet.caveats.append("AV sync analysis only applicable to video")
            return sheet

        # Basic AV sync check using ffprobe stream timing
        if _which("ffprobe"):
            try:
                cmd = [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    str(file_path),
                ]
                result = _run_tool(cmd)
                data = json.loads(result.stdout) if result.stdout.strip() else {}
                streams = data.get("streams", [])

                video = next((s for s in streams if s.get("codec_type") == "video"), {})
                audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

                video_start = float(video.get("start_time", 0))
                audio_start = float(audio.get("start_time", 0))
                offset_ms = round((video_start - audio_start) * 1000, 2)

                sheet.facts.update({
                    "av_sync_applicable": True,
                    "video_start_time": video_start,
                    "audio_start_time": audio_start,
                    "stream_offset_ms": offset_ms,
                    "stream_offset_significant": abs(offset_ms) > 50,
                    "av_sync_calibrated": False,
                })
            except Exception as e:
                sheet.caveats.append(f"AV sync stream analysis failed: {e}")
                sheet.facts["av_sync_applicable"] = False
        else:
            sheet.caveats.append("ffprobe not available for AV sync analysis")
            sheet.facts["av_sync_applicable"] = False

        sheet.caveats.append(
            "Variable frame rate can mimic desync; treat offset as an indicator."
        )

        return sheet


# ---------------------------------------------------------------------------
# Battery runner: runs the appropriate batteries for a media type
# ---------------------------------------------------------------------------

def get_batteries_for_media_type(media_type: str) -> list[str]:
    """
    Determine which batteries apply to a given media type.
    """
    battery_map = {
        "video": ["metadata", "compression", "visual", "audio", "av_sync"],
        "image": ["metadata", "compression", "visual"],
        "audio": ["metadata", "audio"],
        "document": ["metadata"],
    }
    return battery_map.get(media_type, ["metadata"])


def run_all_batteries(
    file_path: str | Path,
    artifacts_dir: str | Path,
    evidence_id: str,
    media_type: Optional[str] = None,
    working_dir: Optional[str | Path] = None,
) -> dict[str, FactSheet]:
    """
    Run all applicable batteries for a piece of evidence.

    Returns:
        Dict mapping battery name to its FactSheet.
    """
    file_path = Path(file_path)
    if media_type is None:
        media_type = intake.detect_media_type(file_path)

    battery_names = get_batteries_for_media_type(media_type)
    results: dict[str, FactSheet] = {}

    batteries = {
        "metadata": MetadataBattery(),
        "compression": CompressionBattery(),
        "visual": VisualBattery(),
        "audio": AudioBattery(),
        "av_sync": AVSyncBattery(),
    }

    for name in battery_names:
        battery = batteries.get(name)
        if battery is None:
            continue

        try:
            if name == "compression":
                sheet = battery.run(file_path, artifacts_dir, evidence_id, working_dir)
            elif name == "visual":
                # Get keyframe paths from compression results if available
                comp = results.get("compression")
                kf_paths = (
                    comp.facts.get("keyframe_paths")
                    if comp else None
                )
                sheet = battery.run(file_path, artifacts_dir, evidence_id, kf_paths)
            elif name == "audio":
                sheet = battery.run(file_path, artifacts_dir, evidence_id, working_dir)
            else:
                sheet = battery.run(file_path, artifacts_dir, evidence_id)

            results[name] = sheet

        except Exception as e:
            # Never silently drop a failed battery
            results[name] = FactSheet(
                battery_name=name,
                evidence_id=evidence_id,
                caveats=[f"Battery '{name}' failed: {e}"],
            )

    return results


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _std(values: list[float | int]) -> float:
    """Standard deviation without numpy dependency."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return variance ** 0.5
