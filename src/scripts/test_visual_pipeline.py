"""
scripts/test_visual_pipeline.py
End-to-end deterministic smoke test for the EMAFIG visual pipeline.

Usage:
    python scripts/test_visual_pipeline.py <image_or_video_path>
    python scripts/test_visual_pipeline.py --selftest

--selftest creates a synthetic PNG and runs the full pipeline without needing
an external evidence file.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.store import CaseStore
from app.engine import InvestigationEngine


# ---------------------------------------------------------------------------
# Coloured terminal output helpers (no external deps)
# ---------------------------------------------------------------------------
_RESET  = "\033[0m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"

def _ok(msg):    print(f"  {_GREEN}[OK]{_RESET} {msg}".encode("ascii","replace").decode())
def _warn(msg):  print(f"  {_YELLOW}[WARN]{_RESET} {msg}".encode("ascii","replace").decode())
def _fail(msg):  print(f"  {_RED}[FAIL]{_RESET} {msg}".encode("ascii","replace").decode())
def _info(msg):  print(f"  {_CYAN}{msg}{_RESET}".encode("ascii","replace").decode())
def _head(msg):  print(f"\n{_BOLD}{msg}{_RESET}".encode("ascii","replace").decode())


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

def check_tools():
    _head("Tool Detection")
    from app.forensics.tooling import resolve_executable
    tools = ["ffmpeg", "ffprobe", "exiftool", "c2patool"]
    results = {}
    for t in tools:
        r = resolve_executable(t)
        results[t] = r
        if r["available"]:
            _ok(f"{t}: {r['path']}  [{r['version'][:80] if r['version'] else 'N/A'}]")
        else:
            _warn(f"{t}: NOT FOUND — {r['error']}")
    return results


def check_python_deps():
    _head("Python Dependencies")
    deps = [
        ("cv2",         "OpenCV"),
        ("numpy",       "NumPy"),
        ("PIL",         "Pillow"),
        ("fastapi",     "FastAPI"),
        ("pydantic",    "Pydantic"),
        ("librosa",     "librosa"),
        ("onnxruntime", "onnxruntime"),
    ]
    for mod, label in deps:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            _ok(f"{label}: {ver}")
        except ImportError as exc:
            _warn(f"{label}: NOT INSTALLED — {exc}")

    # OpenCV Haar cascade check
    try:
        import cv2
        p = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if Path(p).is_file():
            _ok(f"Haar cascade: {p}")
        else:
            _warn(f"Haar cascade XML missing at {p} — face detection will be skipped")
    except Exception as exc:
        _warn(f"Haar cascade check failed: {exc}")


# ---------------------------------------------------------------------------
# Pipeline smoke test
# ---------------------------------------------------------------------------

EXPECTED_IMAGE = {
    "INTAKE":       {"completed"},
    "METADATA":     {"completed", "completed_with_warnings"},
    "VISUAL":       {"completed", "completed_with_warnings"},
    "COMPRESSION":  {"completed", "completed_with_warnings"},
    "AUDIO":        {"completed", "completed_with_warnings", "not_applicable", "failed"},
    "TEMPORAL":     {"not_applicable"},
    "AV_SYNC":      {"not_applicable"},
    "PROVENANCE":   {"completed", "completed_with_warnings"},
}

EXPECTED_VIDEO = {
    "INTAKE":       {"completed"},
    "METADATA":     {"completed", "completed_with_warnings"},
    "VISUAL":       {"completed", "completed_with_warnings"},
    "COMPRESSION":  {"completed", "completed_with_warnings"},
    "AUDIO":        {"completed", "completed_with_warnings", "not_applicable"},
    "TEMPORAL":     {"completed", "completed_with_warnings"},
    "AV_SYNC":      {"completed", "completed_with_warnings", "not_applicable"},
    "PROVENANCE":   {"completed", "completed_with_warnings"},
}

AGENT_MAP = {
    "metadata-analysis":   "METADATA",
    "compression-analysis": "COMPRESSION",
    "visual-forensics":    "VISUAL",
    "audio-forensics":     "AUDIO",
    "temporal-analysis":   "TEMPORAL",
    "av-sync-analysis":    "AV_SYNC",
    "c2pa-provenance":     "PROVENANCE",
}


def run_pipeline(src: Path) -> int:
    """Run the full pipeline on src. Returns 0 for pass, 1 for failure."""
    import tempfile, sqlite3
    td_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    td = td_obj.name
    try:
        store  = CaseStore(Path(td) / "cases")
        engine = InvestigationEngine(store)

        _head(f"Pipeline: {src.name}")
        print(f"  Path:  {src}")
        print(f"  Size:  {src.stat().st_size:,} bytes")

        c = asyncio.run(engine.create_case(src, f"smoke-test: {src.name}"))
        media_type = c.media_type

        _head(f"Agent Status  [media_type={media_type}]")
        expected = EXPECTED_IMAGE if media_type == "image" else EXPECTED_VIDEO
        passed = 0; failed_agents = []

        for agent_id, ar in c.agent_runs.items():
            key = AGENT_MAP.get(agent_id, agent_id.upper().replace("-", "_"))
            ok_statuses = expected.get(key, {"completed", "completed_with_warnings",
                                             "not_applicable", "failed"})
            icon = _ok if ar.status in ok_statuses else _fail
            icon(f"{agent_id:<30} {ar.status:<28} "
                 f"obs={len(ar.observation_ids):<3} arts={len(ar.artifact_ids):<3} "
                 f"dur={ar.duration_ms}ms")
            if ar.status == "failed":
                _fail(f"  error: {ar.error}")
                failed_agents.append(agent_id)
            if ar.warnings:
                for w in ar.warnings:
                    _warn(f"  {w[:100]}")
            if ar.status not in ok_statuses:
                _fail(f"  Expected one of {ok_statuses!r}, got {ar.status!r}")
                failed_agents.append(agent_id)
            else:
                passed += 1

        _head("Observations")
        for o in c.observations:
            _info(f"  {o.observation_id}  {o.type:<40}  calibrated={o.calibrated}")

        _head("Hashes")
        _ok(f"SHA-256: {c.original.sha256}")
        _ok(f"SHA-512: {c.original.sha512}")

        _head("Ledger integrity")
        ledger_result = store.ledger(c.case_id).verify()
        if ledger_result["valid"]:
            _ok(f"Ledger: valid ({ledger_result['entries']} entries)")
        else:
            _fail(f"Ledger: {ledger_result}")

        _head("Evidence gaps")
        for g in c.missing_evidence:
            if g["status"] == "failed":
                _fail(f"  {g['item']}: {g['status']} — {g['impact']}")
            else:
                _warn(f"  {g['item']}: {g['status']}")

        _head("Result")
        if not failed_agents and ledger_result["valid"]:
            print(f"\n  {_GREEN}{_BOLD}PASS{_RESET}  {passed} agents as expected.\n")
            rc = 0
        else:
            print(f"\n  {_RED}{_BOLD}FAIL{_RESET}  "
                  f"Failed agents: {failed_agents or 'none'}; "
                  f"Ledger: {ledger_result['valid']}\n")
            rc = 1
        return rc
    finally:
        # Close SQLite connections before cleanup (Windows file-lock)
        try:
            td_obj.cleanup()
        except Exception:
            pass


def selftest():
    """Create a synthetic PNG and run the full pipeline."""
    import tempfile
    _head("Self-test - generating synthetic JPEG")
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), color=(80, 120, 200)).save(buf, format="JPEG")
    td = tempfile.mkdtemp()
    try:
        src = Path(td) / "selftest.jpg"
        src.write_bytes(buf.getvalue())
        rc = run_pipeline(src)
    finally:
        import shutil
        try:
            shutil.rmtree(td, ignore_errors=True)
        except Exception:
            pass
    return rc


def main():
    check_python_deps()
    check_tools()

    args = sys.argv[1:]
    if not args or args[0] == "--selftest":
        rc = selftest()
    else:
        src = Path(args[0])
        if not src.exists():
            print(f"{_RED}Error: file not found: {src}{_RESET}")
            sys.exit(2)
        rc = run_pipeline(src)

    sys.exit(rc)


if __name__ == "__main__":
    main()
