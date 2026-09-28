"""
EMAFIG Plane C — Module 1: Intake + Hashing

Handles evidence intake: assigns case and evidence IDs, computes SHA-256 hashes,
copies originals to a read-only case folder, records source/platform metadata,
and creates initial ledger and custody entries.

Design decisions:
  - Original files are NEVER modified after intake; they live under original/ as read-only.
  - Every artifact gets a unique ART-xxxx ID and its SHA-256.
  - Derivatives (frames, audio tracks, segments) are placed under working/ with
    their own hashes and parent references.
  - Intake returns a structured EvidenceRecord that Plane B examiners can consume.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASH_ALGORITHM = "sha256"
BUFFER_SIZE = 65_536  # 64 KiB read chunks for hashing large files

# Allowed media extensions (basic validation; not a security boundary)
ALLOWED_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv",  # video
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp",  # image
    ".mp3", ".wav", ".aac", ".ogg", ".flac", ".m4a",  # audio
    ".pdf", ".txt", ".json", ".csv",  # documents / chat exports
}

# Maximum file size (2 GiB) – configurable
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ArtifactRecord:
    """Metadata for any artifact (original, derivative, or tool output)."""
    artifact_id: str
    sha256: str
    file_name: str
    file_path: str
    size_bytes: int
    created_at: str
    producer: str  # "intake" | tool name | Bob mode | "officer"
    producer_version: str
    derived_from: Optional[str] = None  # parent artifact_id
    command_hash: Optional[str] = None  # hash of command used to produce
    run_id: Optional[str] = None
    media_type: Optional[str] = None  # "video" | "image" | "audio" | "document"

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class EvidenceRecord:
    """Top-level record for a piece of evidence in a case."""
    evidence_id: str
    case_id: str
    artifact: ArtifactRecord
    source_url: Optional[str] = None
    platform: Optional[str] = None
    sender_id: Optional[str] = None
    how_received: Optional[str] = None  # "WhatsApp forward", "email", "USB", etc.
    received_at: Optional[str] = None
    seizure_memo_ref: Optional[str] = None
    device_details: Optional[str] = None
    notes: Optional[str] = None
    preservation_fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["artifact"] = self.artifact.to_dict()
        return d


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------

_artifact_counter = 0
_evidence_counter = 0


def _next_artifact_id() -> str:
    """Thread-unsafe counter; replace with DB sequence in production."""
    global _artifact_counter
    _artifact_counter += 1
    return f"ART-{_artifact_counter:04d}"


def _next_evidence_id() -> str:
    global _evidence_counter
    _evidence_counter += 1
    return f"EVD-{_evidence_counter:03d}"


def generate_case_id(prefix: str = "CASE") -> str:
    """Generate a case ID like CASE-2026-001."""
    year = time.strftime("%Y")
    short = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{year}-{short}"


def reset_counters():
    """Reset ID counters (useful for testing)."""
    global _artifact_counter, _evidence_counter
    _artifact_counter = 0
    _evidence_counter = 0


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def sha256_file(path: str | Path) -> str:
    """Compute SHA-256 of a file, streaming in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(BUFFER_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_str(text: str) -> str:
    """Compute SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

def validate_file(path: str | Path) -> list[str]:
    """
    Basic intake validation. Returns a list of problems (empty = OK).
    This is NOT a security boundary — sandboxed tool execution handles that.
    """
    path = Path(path)
    problems = []

    if not path.exists():
        problems.append(f"File does not exist: {path}")
        return problems

    if not path.is_file():
        problems.append(f"Not a regular file: {path}")
        return problems

    size = path.stat().st_size
    if size == 0:
        problems.append("File is empty (0 bytes)")
    if size > MAX_FILE_SIZE:
        problems.append(f"File exceeds {MAX_FILE_SIZE} byte limit: {size} bytes")

    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        problems.append(f"Extension '{ext}' not in allowed list")

    return problems


def detect_media_type(path: str | Path) -> str:
    """Infer media type from extension."""
    ext = Path(path).suffix.lower()
    if ext in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"}:
        return "video"
    if ext in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}:
        return "image"
    if ext in {".mp3", ".wav", ".aac", ".ogg", ".flac", ".m4a"}:
        return "audio"
    return "document"


# ---------------------------------------------------------------------------
# Case folder management
# ---------------------------------------------------------------------------

def create_case_folder(base_dir: str | Path, case_id: str) -> Path:
    """
    Create the standard case folder structure:
        cases/<case_id>/
        ├── original/     # read-only: the file exactly as received
        ├── working/      # derivatives: frames/, audio/, segments/
        ├── artifacts/    # raw tool outputs, Bob outputs
        ├── reports/      # brief, victim guide, certificate draft
        ├── ledger.jsonl
        ├── custody.jsonl
        └── case.sqlite   (created by the orchestrator)
    """
    case_dir = Path(base_dir) / case_id
    for sub in ("original", "working", "working/frames", "working/audio",
                "working/segments", "artifacts", "reports"):
        (case_dir / sub).mkdir(parents=True, exist_ok=True)
    return case_dir


# ---------------------------------------------------------------------------
# Intake pipeline
# ---------------------------------------------------------------------------

def ingest_evidence(
    file_path: str | Path,
    case_dir: str | Path,
    case_id: str,
    *,
    source_url: Optional[str] = None,
    platform: Optional[str] = None,
    sender_id: Optional[str] = None,
    how_received: Optional[str] = None,
    received_at: Optional[str] = None,
    seizure_memo_ref: Optional[str] = None,
    device_details: Optional[str] = None,
    notes: Optional[str] = None,
    preservation_fields: Optional[dict] = None,
) -> EvidenceRecord:
    """
    Full intake pipeline for a single evidence file:
      1. Validate the file
      2. Compute SHA-256
      3. Copy to original/ (read-only)
      4. Assign artifact and evidence IDs
      5. Return an EvidenceRecord (caller writes ledger + custody entries)

    Raises ValueError on validation failure.
    """
    file_path = Path(file_path)
    case_dir = Path(case_dir)

    # 1. Validate
    problems = validate_file(file_path)
    if problems:
        raise ValueError(f"Intake validation failed: {'; '.join(problems)}")

    # 2. Hash
    file_hash = sha256_file(file_path)

    # 3. Copy to original/ and make read-only
    original_dir = case_dir / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    dest = original_dir / file_path.name

    # Prevent overwriting an existing original with the same name
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        dest = original_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

    shutil.copy2(str(file_path), str(dest))

    # Set read-only (best-effort; OS-level enforcement)
    try:
        os.chmod(str(dest), 0o444)
    except OSError:
        pass  # Windows may not fully support this; logged as a limitation

    # 4. Build records
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    art_id = _next_artifact_id()
    evd_id = _next_evidence_id()

    artifact = ArtifactRecord(
        artifact_id=art_id,
        sha256=file_hash,
        file_name=dest.name,
        file_path=str(dest),
        size_bytes=dest.stat().st_size,
        created_at=now,
        producer="intake",
        producer_version="0.1.0",
        media_type=detect_media_type(dest),
    )

    evidence = EvidenceRecord(
        evidence_id=evd_id,
        case_id=case_id,
        artifact=artifact,
        source_url=source_url,
        platform=platform,
        sender_id=sender_id,
        how_received=how_received,
        received_at=received_at,
        seizure_memo_ref=seizure_memo_ref,
        device_details=device_details,
        notes=notes,
        preservation_fields=preservation_fields or {},
    )

    return evidence


def register_derivative(
    file_path: str | Path,
    parent_artifact_id: str,
    producer: str,
    producer_version: str,
    *,
    command_hash: Optional[str] = None,
    run_id: Optional[str] = None,
) -> ArtifactRecord:
    """
    Register a derivative artifact (frame extraction, audio track, etc.).
    The file must already exist at file_path (created by a tool battery).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Derivative file not found: {file_path}")

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return ArtifactRecord(
        artifact_id=_next_artifact_id(),
        sha256=sha256_file(file_path),
        file_name=file_path.name,
        file_path=str(file_path),
        size_bytes=file_path.stat().st_size,
        created_at=now,
        producer=producer,
        producer_version=producer_version,
        derived_from=parent_artifact_id,
        command_hash=command_hash,
        run_id=run_id,
        media_type=detect_media_type(file_path),
    )
