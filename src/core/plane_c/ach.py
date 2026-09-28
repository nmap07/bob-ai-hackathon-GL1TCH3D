"""
EMAFIG Plane C — Module 6: Analysis of Competing Hypotheses (ACH)

Deterministic ACH matrix builder and ranker. The hypothesis-assessor (Plane B)
proposes cell values; this module validates, identifies non-diagnostic rows,
ranks hypotheses by fewest inconsistencies, and produces the matrix for display.

Key rules:
  1. Cells are C (consistent), I (inconsistent), or N (not applicable).
  2. A row whose non-N cells are ALL identical is non-diagnostic and greyed out.
  3. Hypotheses are ranked by fewest I cells (ACH's core: disprove, don't confirm).
  4. Output is a matrix and a ranking, NEVER a probability.
  5. The brief may say "more consistent with H2 than H1" but not "78% fake".

The analyst can edit any cell; edits are recorded in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

DEFAULT_HYPOTHESES = [
    {"id": "H1", "label": "Authentic recording"},
    {"id": "H2", "label": "Manipulated face or content"},
    {"id": "H3", "label": "Fully synthetic or generated media"},
    {"id": "H4", "label": "Authentic with benign post-processing (platform recompression, legitimate edit)"},
    {"id": "H5", "label": "Manipulated, then re-encoded"},
    {"id": "H6", "label": "Audio-only manipulation (voice clone over genuine video, or audio splice)"},
    {"id": "H7", "label": "Screen recording of a live or real-time deepfake call"},
]

VALID_CELLS = {"C", "I", "N"}


# ---------------------------------------------------------------------------
# ACH Matrix
# ---------------------------------------------------------------------------

@dataclass
class ACHCell:
    """A single cell in the ACH matrix."""
    group_id: str
    hypothesis_id: str
    value: str  # "C" | "I" | "N"
    reason: str = ""
    proposed_by: str = "hypothesis-assessor"  # or "analyst"
    edited: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ACHMatrix:
    """
    The full ACH matrix with rows (independence groups) and columns (hypotheses).
    """
    hypotheses: list[dict] = field(default_factory=lambda: list(DEFAULT_HYPOTHESES))
    cells: dict[str, dict[str, ACHCell]] = field(default_factory=dict)
    # cells[group_id][hypothesis_id] = ACHCell

    def hypothesis_ids(self) -> list[str]:
        return [h["id"] for h in self.hypotheses]

    def add_hypothesis(self, hypothesis_id: str, label: str):
        """Add a custom hypothesis (analyst-defined)."""
        if any(h["id"] == hypothesis_id for h in self.hypotheses):
            raise ValueError(f"Hypothesis {hypothesis_id} already exists")
        self.hypotheses.append({"id": hypothesis_id, "label": label})

    def set_cell(
        self,
        group_id: str,
        hypothesis_id: str,
        value: str,
        reason: str = "",
        proposed_by: str = "hypothesis-assessor",
    ):
        """Set a cell value. Validates the value."""
        value = value.upper()
        if value not in VALID_CELLS:
            raise ValueError(
                f"Invalid cell value '{value}'. Must be one of: {VALID_CELLS}"
            )
        if hypothesis_id not in self.hypothesis_ids():
            raise ValueError(f"Unknown hypothesis: {hypothesis_id}")

        if group_id not in self.cells:
            self.cells[group_id] = {}

        self.cells[group_id][hypothesis_id] = ACHCell(
            group_id=group_id,
            hypothesis_id=hypothesis_id,
            value=value,
            reason=reason,
            proposed_by=proposed_by,
            edited=(proposed_by != "hypothesis-assessor"),
        )

    def get_cell(self, group_id: str, hypothesis_id: str) -> Optional[ACHCell]:
        """Get a cell value."""
        return self.cells.get(group_id, {}).get(hypothesis_id)

    def load_proposals(self, proposals: list[dict]):
        """
        Load cell proposals from the hypothesis-assessor (Plane B).

        Expected format:
        [
            {
                "group_id": "DRV-004:face_boundary",
                "hypothesis_id": "H1",
                "value": "I",
                "reason": "Face boundary artifacts are inconsistent with..."
            },
            ...
        ]
        """
        for p in proposals:
            gid = p.get("group_id", "")
            hid = p.get("hypothesis_id", "")
            val = p.get("value", "N")
            reason = p.get("reason", "")

            if not gid or not hid:
                continue

            try:
                self.set_cell(gid, hid, val, reason, "hypothesis-assessor")
            except ValueError:
                # Skip invalid cells (logged elsewhere)
                continue

    def edit_cell(
        self,
        group_id: str,
        hypothesis_id: str,
        value: str,
        reason: str = "",
        editor: str = "analyst",
    ):
        """Edit a cell (analyst override). Marked as edited for audit."""
        self.set_cell(group_id, hypothesis_id, value, reason, editor)


# ---------------------------------------------------------------------------
# Non-diagnostic row detection
# ---------------------------------------------------------------------------

def find_non_diagnostic_rows(matrix: ACHMatrix) -> set[str]:
    """
    A row is non-diagnostic if all its non-N cells have the same value.
    E.g., if every hypothesis is "C" (consistent), the observation doesn't
    help distinguish between them.

    Returns: set of group_ids that are non-diagnostic.
    """
    non_diagnostic = set()

    for group_id, row in matrix.cells.items():
        non_n_values = set()
        for hid in matrix.hypothesis_ids():
            cell = row.get(hid)
            if cell and cell.value != "N":
                non_n_values.add(cell.value)

        # If all non-N cells are identical (or there are no non-N cells)
        if len(non_n_values) <= 1:
            non_diagnostic.add(group_id)

    return non_diagnostic


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank_hypotheses(matrix: ACHMatrix) -> dict:
    """
    Rank hypotheses by fewest inconsistencies (I cells) across diagnostic rows.

    ACH's core idea: try to disprove hypotheses rather than accumulate
    confirmations. The hypothesis with the fewest I cells is the most
    consistent with the evidence.

    Returns:
        {
            "ranking": ["H4", "H2", ...],  # best (fewest I) to worst
            "scores": {"H1": 3, "H2": 1, ...},  # I-cell counts
            "non_diagnostic_groups": ["group1", ...],
            "diagnostic_groups": ["group2", ...],
        }
    """
    non_diagnostic = find_non_diagnostic_rows(matrix)
    diagnostic_groups = set(matrix.cells.keys()) - non_diagnostic

    hyp_ids = matrix.hypothesis_ids()
    scores: dict[str, int] = {h: 0 for h in hyp_ids}

    for group_id in diagnostic_groups:
        row = matrix.cells.get(group_id, {})
        for hid in hyp_ids:
            cell = row.get(hid)
            if cell and cell.value == "I":
                scores[hid] += 1

    # Sort by fewest inconsistencies (ascending)
    ranking = sorted(hyp_ids, key=lambda h: scores[h])

    return {
        "ranking": ranking,
        "scores": scores,
        "non_diagnostic_groups": sorted(non_diagnostic),
        "diagnostic_groups": sorted(diagnostic_groups),
        "total_groups": len(matrix.cells),
    }


# ---------------------------------------------------------------------------
# Missing-evidence checklist (deterministic)
# ---------------------------------------------------------------------------

MISSING_EVIDENCE_CHECKLIST = [
    {
        "item": "original_device",
        "label": "Original recording device",
        "action": "Request seizure of the device that captured or first received the media",
        "category": "device",
    },
    {
        "item": "original_file",
        "label": "Original unmodified file (before any forwarding/compression)",
        "action": "Request the earliest copy from the source device or platform",
        "category": "file",
    },
    {
        "item": "source_url",
        "label": "Source URL or first-upload location",
        "action": "Check platform upload history, reverse image/video search",
        "category": "provenance",
    },
    {
        "item": "first_upload_trace",
        "label": "First-upload trace and timeline",
        "action": "Request platform data via legal process (Section 91 CrPC / 94 BNSS)",
        "category": "provenance",
    },
    {
        "item": "c2pa_manifest",
        "label": "C2PA/Content Credentials manifest",
        "action": "Check the file for C2PA metadata; note that absence is NOT evidence of manipulation",
        "category": "provenance",
    },
    {
        "item": "second_copy",
        "label": "Second independent copy from a different source",
        "action": "Search for the same content on other platforms or from other recipients",
        "category": "corroboration",
    },
    {
        "item": "chat_context",
        "label": "Chat messages / conversation context",
        "action": "Preserve chat exports showing how the media was shared, with timestamps",
        "category": "context",
    },
    {
        "item": "payment_trail",
        "label": "Payment records (UPI IDs, bank references)",
        "action": "Collect transaction records linking demands to accounts",
        "category": "financial",
    },
    {
        "item": "call_logs",
        "label": "Call logs and communication records",
        "action": "Request CDR/call history from the telecom provider",
        "category": "communication",
    },
    {
        "item": "sender_identity",
        "label": "Verified sender identity and platform account details",
        "action": "Collect platform profile, registration details, linked accounts",
        "category": "identity",
    },
]


def check_missing_evidence(case_record: dict) -> list[dict]:
    """
    Check what evidence is missing based on the case record.

    Args:
        case_record: dict with keys matching checklist items, values are
                     True/False/"collected"/"unavailable"/"not_applicable"

    Returns:
        List of missing items with their suggested actions.
    """
    collected = case_record.get("collected_evidence", {})
    missing = []

    for item in MISSING_EVIDENCE_CHECKLIST:
        key = item["item"]
        status = collected.get(key, False)

        if status in (True, "collected"):
            continue
        if status == "not_applicable":
            continue

        entry = {
            **item,
            "status": status if status else "missing",
        }

        # Special case: C2PA absence must never be scored as evidence
        if key == "c2pa_manifest":
            entry["note"] = (
                "Absence of a C2PA credential is listed as a gap, "
                "not as evidence of fakery."
            )

        missing.append(entry)

    return missing


# ---------------------------------------------------------------------------
# Matrix export for reporting
# ---------------------------------------------------------------------------

def export_matrix(
    matrix: ACHMatrix,
    group_summaries: Optional[list[dict]] = None,
) -> dict:
    """
    Export the full ACH matrix as a report-ready dict.

    Returns a dict with:
      - hypotheses (list of {id, label})
      - rows (list of {group_id, cells: {H1: {value, reason}, ...}, diagnostic: bool})
      - ranking
      - non_diagnostic_groups
    """
    non_diagnostic = find_non_diagnostic_rows(matrix)
    ranking_result = rank_hypotheses(matrix)

    # Build group label lookup
    group_labels = {}
    if group_summaries:
        for gs in group_summaries:
            group_labels[gs["group_id"]] = gs

    rows = []
    for group_id in sorted(matrix.cells.keys()):
        row_cells = {}
        for hid in matrix.hypothesis_ids():
            cell = matrix.cells[group_id].get(hid)
            if cell:
                row_cells[hid] = {
                    "value": cell.value,
                    "reason": cell.reason,
                    "edited": cell.edited,
                }
            else:
                row_cells[hid] = {"value": "N", "reason": "", "edited": False}

        row = {
            "group_id": group_id,
            "cells": row_cells,
            "diagnostic": group_id not in non_diagnostic,
        }

        # Add group summary info if available
        gs = group_labels.get(group_id)
        if gs:
            row["family"] = gs.get("family", "")
            row["observation_ids"] = gs.get("observation_ids", [])
            row["observation_count"] = gs.get("observation_count", 0)

        rows.append(row)

    return {
        "hypotheses": matrix.hypotheses,
        "rows": rows,
        "ranking": ranking_result,
    }
