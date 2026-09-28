
from __future__ import annotations
import hashlib, json, mimetypes, os, platform, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"

def sha256_file(path: Path, chunk: int = 1024*1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()

def sha512_file(path: Path, chunk: int = 1024*1024) -> str:
    h = hashlib.sha512()
    with path.open("rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

def run_cmd(cmd: list[str], timeout: int = 120, cwd: str | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("HTTP_PROXY", None); env.pop("HTTPS_PROXY", None)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", f"timeout: {e}"

def tool_version(tool: str) -> str:
    flags = {"ffmpeg":["-version"],"ffprobe":["-version"],"c2patool":["-V"],"exiftool":["-ver"]}
    rc,out,err = run_cmd([tool] + flags.get(tool, ["--version"]), timeout=10)
    return (out or err).splitlines()[0][:250] if (out or err) else "unavailable"

def environment_identity() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }

def safe_name(name: str) -> str:
    return Path(name).name.replace("\x00", "")[:255]

IMAGE_EXTS = {".jpg",".jpeg",".png",".webp",".bmp",".tif",".tiff",".gif"}
VIDEO_EXTS = {".mp4",".mov",".mkv",".avi",".webm",".m4v",".3gp",".mts",".m2ts",".mpeg",".mpg"}
AUDIO_EXTS = {".wav",".mp3",".m4a",".aac",".flac",".ogg",".opus",".amr"}

def _probe(path: Path) -> dict | None:
    """Return ffprobe format+streams, or None when ffprobe is unavailable or fails."""
    from app.forensics.tooling import resolve_executable
    tool = resolve_executable("ffprobe")
    if not tool["available"]:
        return None
    rc, out, _ = run_cmd([tool["path"], "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
                          str(path)], timeout=30)
    if rc != 0:
        return None
    try:
        return json.loads(out or "{}")
    except json.JSONDecodeError:
        return None

def media_type(path: Path) -> str:
    """Classify evidence as image / video / audio.

    Containers are ambiguous (WhatsApp voice notes arrive as .mpeg, audio-only
    .mp4/.webm exist), so non-image files are sniffed with ffprobe and the
    extension is only a fallback.
    """
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS: return "image"
    info = _probe(path) if path.exists() else None
    streams = (info or {}).get("streams") or []
    fmt = ((info or {}).get("format") or {}).get("format_name", "")
    if streams and (fmt == "image2" or fmt.endswith("_pipe")):
        return "image"      # a still image inside an unknown extension
    if streams:
        has_video = any(s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
                        for s in streams)
        if has_video: return "video"
        if any(s.get("codec_type") == "audio" for s in streams): return "audio"
    if ext in VIDEO_EXTS: return "video"
    if ext in AUDIO_EXTS: return "audio"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
