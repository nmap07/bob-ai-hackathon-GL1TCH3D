"""
EMAFIG Plane C — Trust Services (No LLM)

Deterministic, cryptographic, and tool-based services for digital evidence
forensic analysis. Every module in this plane operates without any LLM calls.

Modules:
    intake          – Evidence intake, ID assignment, SHA-256 hashing, read-only sealing
    ledger          – Append-only hash-chained JSONL ledger
    custody         – Chain-of-custody transfer log
    tool_batteries  – Deterministic tool runners (ffprobe, exiftool, ffmpeg, OpenCV, librosa)
    independence    – Observation independence grouping
    ach             – Analysis of Competing Hypotheses matrix builder and ranker
    legal_engine    – Rules-based legal section mapper (no LLM)
    citation_check  – Deterministic citation and forbidden-phrase checker
    certificate     – BSA 2023 Section 63(4) certificate generator
    linker          – Cross-case fingerprint store and cluster proposer
"""

__version__ = "0.1.0"
__all__ = [
    "intake",
    "ledger",
    "custody",
    "tool_batteries",
    "independence",
    "ach",
    "legal_engine",
    "citation_check",
    "certificate",
    "linker",
]
