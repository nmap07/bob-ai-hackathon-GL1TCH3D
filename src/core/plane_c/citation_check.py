"""
EMAFIG Plane C — Module 8: Citation Checker

Deterministic half of the Verifier: checks that every evidence sentence in a
draft carries valid citations, that cited observations exist and are not rejected,
that legal sentences cite valid RULE-IDs from the rules table, and that no
forbidden phrasing appears without a calibrated basis.

This module runs as plain code (no LLM). The entailment check (whether the
sentence is *supported by* and *no stronger than* the cited observation) is
done by the Verifier Bob mode in Plane B.

Forbidden phrases (without calibrated basis):
  "proves", "is fake", "confirmed deepfake", "definitely", percentages

Allowed phrases:
  "indicator", "more consistent with", "not tested", "unresolved"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Citation pattern: [OBS-00021] or [ART-0031] or [RULE-extortion.308]
CITE_PATTERN = re.compile(
    r"\[((?:OBS|ART)-[0-9A-Za-z]+|RULE-[\w.]+)\]"
)

# Forbidden phrasing without calibrated basis
FORBIDDEN_PATTERN = re.compile(
    r"\b(proves?|is\s+fake|confirmed\s+deepfake|definitely|conclusively|"
    r"undeniably|without\s+doubt|certainly\s+fake|proven\s+manipulat)"
    r"\b|\d+\s?%",
    re.IGNORECASE,
)

# Allowed calibrated-exception phrases
CALIBRATED_EXCEPTION = re.compile(
    r"\bcalibrated\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SentenceCheck:
    """Result of checking a single sentence."""
    index: int
    sentence: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    cited_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationReport:
    """Full verification report for a draft."""
    total_sentences: int
    passed: int
    failed: int
    results: list[SentenceCheck] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_sentences if self.total_sentences > 0 else 0.0

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict:
        return {
            "total_sentences": self.total_sentences,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "all_passed": self.all_passed,
            "results": [r.to_dict() for r in self.results],
        }

    def failed_sentences(self) -> list[SentenceCheck]:
        return [r for r in self.results if not r.passed]


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class CitationChecker:
    """
    Deterministic citation and phrasing checker.

    Usage:
        checker = CitationChecker(observations, rule_ids)
        report = checker.check_draft(sentences)
        if not report.all_passed:
            for fail in report.failed_sentences():
                print(f"Sentence {fail.index}: {fail.problems}")
    """

    def __init__(
        self,
        observations: list[dict],
        rule_ids: set[str],
        artifact_ids: Optional[set[str]] = None,
        require_confirmed: bool = False,
    ):
        """
        Args:
            observations: list of observation dicts with 'obs_id' and
                         'review' -> 'status' fields
            rule_ids: set of valid RULE-xxx IDs from the legal rules engine
        """
        self.observations = {
            obs["obs_id"]: obs for obs in observations
            if "obs_id" in obs
        }
        # Also index ART-IDs if present
        self.artifacts = set()
        for obs in observations:
            tool_run = obs.get("tool_run", {})
            art_id = tool_run.get("output_artifact")
            if art_id:
                self.artifacts.add(art_id)

        self.artifacts |= set(artifact_ids or ())
        self.rule_ids = rule_ids
        # A brief may rely only on analyst-confirmed observations (plan §4.3).
        self.require_confirmed = require_confirmed

    def check_sentence(self, index: int, sentence: str) -> SentenceCheck:
        """Check a single sentence for citation and phrasing issues."""
        problems = []
        sentence = sentence.strip()

        # Skip empty sentences and section headers
        if not sentence or sentence.startswith("#") or sentence.startswith("---"):
            return SentenceCheck(
                index=index,
                sentence=sentence,
                passed=True,
                cited_ids=[],
            )

        # 1. Extract citations
        cited_ids = CITE_PATTERN.findall(sentence)

        # 2. Check: every evidence sentence must have at least one citation
        # (Allow non-evidence sentences like transition phrases)
        is_evidence_sentence = self._is_evidence_sentence(sentence)
        if is_evidence_sentence and not cited_ids:
            problems.append("Evidence sentence has no citation")

        # 3. Validate each cited ID
        for cid in cited_ids:
            if cid.startswith("OBS-"):
                if cid not in self.observations:
                    problems.append(f"{cid} not found in observations")
                else:
                    obs = self.observations[cid]
                    status = obs.get("review", {}).get("status", "pending")
                    if status == "rejected":
                        problems.append(f"{cid} has been rejected")
                    elif self.require_confirmed and status != "confirmed":
                        problems.append(f"{cid} has not been confirmed by an analyst")

            elif cid.startswith("ART-"):
                # ART references are valid as long as they exist
                if cid not in self.artifacts and cid not in self.observations:
                    problems.append(f"{cid} not found in artifacts or observations")

            elif cid.startswith("RULE-"):
                if cid not in self.rule_ids:
                    problems.append(f"{cid} not found in rules table")

        # 4. Check for forbidden phrasing
        forbidden_match = FORBIDDEN_PATTERN.search(sentence)
        if forbidden_match:
            # Exception: allowed if "calibrated" is mentioned in the same sentence
            if not CALIBRATED_EXCEPTION.search(sentence):
                matched = forbidden_match.group()
                problems.append(
                    f"Forbidden phrasing without calibrated basis: '{matched}'"
                )

        return SentenceCheck(
            index=index,
            sentence=sentence,
            passed=len(problems) == 0,
            problems=problems,
            cited_ids=cited_ids,
        )

    def check_draft(self, sentences: list[str]) -> VerificationReport:
        """
        Check an entire draft (list of sentences).

        Returns a VerificationReport with per-sentence results.
        """
        results = []
        for i, s in enumerate(sentences):
            result = self.check_sentence(i, s)
            results.append(result)

        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        return VerificationReport(
            total_sentences=len(sentences),
            passed=passed,
            failed=failed,
            results=results,
        )

    def check_text(self, text: str) -> VerificationReport:
        """
        Check a full text block, splitting on sentence boundaries.
        Uses a simple sentence splitter (period, exclamation, question mark
        followed by space or end).
        """
        sentences = self._split_sentences(text)
        return self.check_draft(sentences)

    # ---- helpers ---------------------------------------------------------

    def _is_evidence_sentence(self, sentence: str) -> bool:
        """
        Heuristic to determine if a sentence is making an evidence claim
        (and therefore must have citations).

        Non-evidence sentences include:
          - Section headings
          - Transition phrases ("The following observations were made:")
          - Metadata lines (case ID, date)
          - Boilerplate language
        """
        lower = sentence.lower().strip()

        # Obvious non-evidence patterns
        non_evidence_patterns = [
            "the following", "this section", "this report",
            "case id", "case number", "date of",
            "prepared by", "signed by", "note:",
            "see also", "refer to", "as described",
            "the analysis", "this certificate", "table of contents",
        ]
        for pattern in non_evidence_patterns:
            if lower.startswith(pattern):
                return False

        # Short sentences (< 20 chars) are likely headers or labels
        if len(sentence) < 20:
            return False

        # Evidence indicators (words that suggest a claim is being made)
        evidence_indicators = [
            "indicat", "consistent", "inconsistent", "suggest",
            "observ", "detect", "found", "show", "reveal",
            "artifact", "anomal", "discrepanc", "manipulat",
            "authentic", "synthetic", "generated", "modified",
            "metadata", "compression", "boundary", "spectral",
            "offset", "discontinuit", "splice", "clone",
        ]
        for indicator in evidence_indicators:
            if indicator in lower:
                return True

        # If the sentence is long enough, assume it might be evidence
        return len(sentence) > 60

    def _split_sentences(self, text: str) -> list[str]:
        """Simple sentence splitter."""
        # Split on newlines first (each line may be a sentence or heading)
        lines = text.strip().split("\n")
        sentences = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Further split on sentence-ending punctuation
            parts = re.split(r'(?<=[.!?])\s+', line)
            sentences.extend(p.strip() for p in parts if p.strip())
        return sentences
