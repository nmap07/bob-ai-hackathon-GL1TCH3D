"""
EMAFIG Plane C — Module 2: Hash-Chained Ledger

Append-only JSONL ledger where each entry's hash commits to all previous entries.
This provides tamper-evidence (not tamper-proofing) for the forensic record.

Entry types:
    artifact     – a file was created or received
    tool_run     – a deterministic tool produced output
    agent_run    – a Bob mode produced output
    human_action – an officer confirmed, rejected, or edited something
    custody      – a custody transfer occurred
    report       – a report was generated
    seal         – the case was sealed (no further entries expected)

Verification:
    hash = SHA-256(prev_hash + canonical_json(entry_without_hash))
    The chain can be independently verified by recomputing from entry #1.

What the ledger proves and does not prove:
    PROVES:   the sequence and content of recorded events were not altered after the fact.
    DOES NOT: prove the original evidence was authentic.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Canonical JSON serialization (deterministic)
# ---------------------------------------------------------------------------

def canonical_json(obj: Any) -> str:
    """
    Deterministic JSON: sorted keys, no extra whitespace, no ASCII escaping.
    This ensures the same object always hashes to the same value.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Ledger entry types
# ---------------------------------------------------------------------------

ENTRY_TYPES = frozenset({
    "artifact", "tool_run", "agent_run", "human_action",
    "custody", "report", "seal",
})


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class Ledger:
    """
    Append-only hash-chained JSONL ledger for forensic audit trails.

    Usage:
        ledger = Ledger("cases/CASE-2026-001/ledger.jsonl")
        entry = ledger.append(
            type_="artifact",
            actor={"kind": "tool", "id": "intake", "version": "0.1.0"},
            ref="ART-0001",
            sha256="abcdef...",
        )
        assert ledger.verify()
        print(ledger.head())
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    # ---- internal helpers ------------------------------------------------

    def _read_last_entry(self) -> Optional[dict]:
        """Read the last entry from the ledger file."""
        last = None
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last = json.loads(stripped)
        return last

    def _compute_hash(self, prev: str, entry: dict) -> str:
        """Compute the chain hash: SHA-256(prev + canonical(entry))."""
        payload = prev + canonical_json(entry)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ---- public API ------------------------------------------------------

    def append(
        self,
        type_: str,
        actor: dict,
        ref: str,
        sha256: str,
        **extra: Any,
    ) -> dict:
        """
        Append a new entry to the ledger.

        Args:
            type_:   one of ENTRY_TYPES
            actor:   {"kind": "tool"|"agent"|"officer", "id": "...", "version": "..."}
            ref:     reference ID (artifact, observation, evidence, etc.)
            sha256:  hash of the referenced object
            **extra: additional fields (e.g., command_hash, input_hash)

        Returns:
            The complete entry dict including its computed hash.

        Raises:
            ValueError if type_ is not a valid entry type.
        """
        if type_ not in ENTRY_TYPES:
            raise ValueError(
                f"Invalid entry type '{type_}'. Must be one of: {', '.join(sorted(ENTRY_TYPES))}"
            )

        last = self._read_last_entry()
        prev = last["hash"] if last else "0" * 64
        seq = (last["seq"] + 1) if last else 1

        entry = {
            "seq": seq,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": type_,
            "actor": actor,
            "ref": ref,
            "sha256": sha256,
            **extra,
            "prev": prev,
        }

        # Compute the chain hash over (prev + canonical(entry_without_hash))
        entry["hash"] = self._compute_hash(prev, entry)

        # Append atomically (as atomic as JSONL gets without fsync)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical_json(entry) + "\n")

        return entry

    def verify(self) -> tuple[bool, int, Optional[str]]:
        """
        Verify the entire chain from entry #1.

        Returns:
            (valid, entries_checked, error_message_or_None)
        """
        prev = "0" * 64
        count = 0

        with self.path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue

                e = json.loads(stripped)
                count += 1
                claimed_hash = e.pop("hash")

                # Check prev pointer
                if e.get("prev") != prev:
                    return (
                        False, count,
                        f"Entry #{e.get('seq', '?')} (line {line_num}): "
                        f"prev mismatch (expected {prev[:16]}..., got {e.get('prev', 'MISSING')[:16]}...)"
                    )

                # Recompute hash
                computed = self._compute_hash(prev, e)
                if computed != claimed_hash:
                    return (
                        False, count,
                        f"Entry #{e.get('seq', '?')} (line {line_num}): "
                        f"hash mismatch (expected {computed[:16]}..., got {claimed_hash[:16]}...)"
                    )

                prev = claimed_hash

        return (True, count, None)

    def head(self) -> Optional[str]:
        """Return the hash of the last ledger entry (the 'ledger head')."""
        last = self._read_last_entry()
        return last["hash"] if last else None

    def entries(self) -> list[dict]:
        """Read all entries (for small ledgers; use streaming for large ones)."""
        result = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    result.append(json.loads(stripped))
        return result

    def count(self) -> int:
        """Count ledger entries."""
        n = 0
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
        return n

    def seal(self, officer_id: str, officer_name: str) -> dict:
        """
        Seal the ledger: appends a 'seal' entry that marks the end of the case.
        The report should include the hash from this entry as the final ledger head.
        """
        return self.append(
            type_="seal",
            actor={"kind": "officer", "id": officer_id, "version": "n/a"},
            ref="LEDGER",
            sha256=self.head() or ("0" * 64),
            sealed_by=officer_name,
        )

    def summary(self) -> dict:
        """
        Generate a ledger summary for the drafter/report.
        Counts entries by type and returns the head.
        """
        type_counts: dict[str, int] = {}
        total = 0
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    e = json.loads(stripped)
                    t = e.get("type", "unknown")
                    type_counts[t] = type_counts.get(t, 0) + 1
                    total += 1

        return {
            "total_entries": total,
            "entries_by_type": type_counts,
            "ledger_head": self.head(),
            "chain_verified": self.verify()[0],
        }
