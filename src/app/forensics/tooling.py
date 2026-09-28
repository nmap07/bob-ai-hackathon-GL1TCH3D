"""
app/forensics/tooling.py
Reusable Windows-aware executable resolver for EMAFIG forensic tools.
Never hard-codes a single install path — uses shutil.which() first,
then walks common Windows installation directories.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Known Windows search paths for common forensic tools
# ---------------------------------------------------------------------------
_WINDOWS_HINTS: dict[str, list[str]] = {
    "ffmpeg": [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\Tools\ffmpeg\bin\ffmpeg.exe",
    ],
    "ffprobe": [
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
        r"C:\Tools\ffmpeg\bin\ffprobe.exe",
    ],
    "exiftool": [
        r"C:\Windows\exiftool.exe",
        r"C:\Program Files\ExifTool\exiftool.exe",
        r"C:\Program Files (x86)\ExifTool\exiftool.exe",
        r"C:\Tools\exiftool\exiftool.exe",
        r"C:\ExifTool\exiftool.exe",
    ],
    "c2patool": [
        r"C:\Program Files\c2patool\c2patool.exe",
        r"C:\Tools\c2patool\c2patool.exe",
    ],
}

# Version-probe flags per tool
_VERSION_FLAGS: dict[str, list[str]] = {
    "ffmpeg":   ["-version"],
    "ffprobe":  ["-version"],
    "exiftool": ["-ver"],
    "c2patool": ["-V"],
}


def _probe_version(exe_path: str, tool: str) -> str:
    flags = _VERSION_FLAGS.get(tool, ["--version"])
    try:
        result = subprocess.run(
            [exe_path] + flags,
            capture_output=True, text=True, timeout=10,
            env={**os.environ},
        )
        output = (result.stdout or result.stderr or "").strip()
        return output.splitlines()[0][:250] if output else "unknown"
    except Exception as exc:
        return f"version-probe-failed: {exc}"


@lru_cache(maxsize=32)
def resolve_executable(tool: str) -> dict[str, Any]:
    """
    Resolve a forensic tool executable on the current system.

    Returns:
        {
            "available": bool,
            "path": str | None,
            "version": str | None,
            "error": str | None,
        }
    """
    # 1. Honour environment override (e.g. FFMPEG_PATH, EXIFTOOL_PATH)
    env_key = tool.upper().replace("-", "_") + "_PATH"
    env_override = os.environ.get(env_key)
    if env_override and Path(env_override).is_file():
        return {
            "available": True,
            "path": env_override,
            "version": _probe_version(env_override, tool),
            "error": None,
        }

    # 2. shutil.which() — covers PATH on all platforms
    found = shutil.which(tool)
    if not found:
        # Also try <tool>.exe on Windows
        found = shutil.which(tool + ".exe")
    if found:
        return {
            "available": True,
            "path": found,
            "version": _probe_version(found, tool),
            "error": None,
        }

    # 3. Walk Windows hint paths
    for hint in _WINDOWS_HINTS.get(tool, []):
        if Path(hint).is_file():
            return {
                "available": True,
                "path": hint,
                "version": _probe_version(hint, tool),
                "error": None,
            }

    return {
        "available": False,
        "path": None,
        "version": None,
        "error": f"'{tool}' executable not found on PATH or known Windows locations.",
    }


def run_tool(
    cmd: list[str],
    *,
    timeout: int = 120,
    cwd: str | None = None,
) -> dict[str, Any]:
    """
    Run an external tool and return a structured result envelope.
    Redacts nothing sensitive here (no secrets in EMAFIG tool calls),
    but records all diagnostics needed for court-ready audit.
    """
    start = time.monotonic()
    env = os.environ.copy()
    # Strip proxy vars that can cause unexpected network calls
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(key, None)

    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        rc = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except FileNotFoundError as exc:
        rc = 127
        stdout = ""
        stderr = str(exc)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        rc = 124
        stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = f"timeout after {timeout}s"

    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "executable": cmd[0] if cmd else "",
        "command": cmd,
        "returncode": rc,
        "stdout": stdout,
        "stderr": stderr[-4000:],  # cap at 4 kB for storage
        "duration_ms": duration_ms,
        "timed_out": timed_out,
    }
