"""
EMAFIG Plane C — Module 7: Legal Rules Engine

A versioned rules table that maps case circumstances to IT Act 2000 / BNS 2023
sections. This is NOT an LLM — it is a deterministic engine that:

  1. Receives circumstance keys from the legal-proposer (Plane B)
  2. Checks preconditions against case facts
  3. Emits candidate sections with verification status
  4. Flags provisions whose wording may not fit (e.g., gender-specific provisions)
  5. Lists evidence still needed per section

Output policy:
  - Sections appear ONLY from this rules table.
  - Bob may explain why a circumstance applies but may NOT introduce a section number.
  - The Verifier rejects any section number not in this table.
  - Every output says "may be relevant", never "should be charged with".
  - The system never states that a person should be charged.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Verification status
# ---------------------------------------------------------------------------

class VerificationStatus:
    """Verification status for a legal provision."""
    VERIFIED_PRIMARY = "verified_primary"      # Confirmed on India Code / official text
    VERIFIED_SECONDARY = "verified_secondary"  # Seen on secondary source (LiveLaw, etc.)
    UNVERIFIED = "unverified"                  # Not yet verified
    DISPUTED = "disputed"                      # Application to deepfakes is unsettled

    ALL = frozenset({
        VERIFIED_PRIMARY, VERIFIED_SECONDARY, UNVERIFIED, DISPUTED,
    })


# ---------------------------------------------------------------------------
# Rules table (versioned)
# ---------------------------------------------------------------------------

RULES_TABLE_VERSION = "2026-09-28-v1"

RULES_TABLE: list[dict] = [
    {
        "key": "extortion",
        "label": "Used for blackmail or sextortion",
        "preconditions": {
            "demand_made": True,
        },
        "bns": [
            {"section": "308", "title": "Extortion",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "Section 308's illustration covers a threat to publish a defamatory libel unless money is paid."},
            {"section": "351", "title": "Criminal intimidation",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "Includes threats to reputation."},
        ],
        "it_act": [],
        "evidence_needed": [
            "threat messages", "demand (money/content)", "payment records", "timeline",
        ],
        "notes": "IT Act 66E concerns privacy violation; do NOT cite it as the extortion basis.",
        "gender_restriction": None,
        "source_url": "https://devgan.in/bns/section/308/",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "impersonation",
        "label": "Impersonation to defraud",
        "preconditions": {
            "impersonation_detected": True,
        },
        "bns": [
            {"section": "319(2)", "title": "Cheating by personation",
             "status": VerificationStatus.VERIFIED_SECONDARY},
            {"section": "318", "title": "Cheating",
             "status": VerificationStatus.UNVERIFIED},
        ],
        "it_act": [
            {"section": "66C", "title": "Identity theft",
             "status": VerificationStatus.VERIFIED_SECONDARY},
            {"section": "66D", "title": "Cheating by personation using a computer resource",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "evidence_needed": [
            "evidence of impersonation", "victim identification",
            "proof of deception", "financial loss if applicable",
        ],
        "notes": "",
        "gender_restriction": None,
        "source_url": "",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "false_electronic_record",
        "label": "False electronic record presented as genuine",
        "preconditions": {
            "manipulation_detected": True,
        },
        "bns": [
            {"section": "336", "title": "Forgery (definition covers false electronic records)",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "Application to deepfakes is unsettled."},
        ],
        "it_act": [
            {"section": "66", "title": "Computer-related offences",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "evidence_needed": [
            "evidence of manipulation", "evidence of presentation as genuine",
        ],
        "notes": "Application of forgery provisions to deepfakes is legally unsettled.",
        "gender_restriction": None,
        "source_url": "",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "non_consensual_intimate",
        "label": "Non-consensual intimate content",
        "preconditions": {
            "intimate_content": True,
        },
        "bns": [
            {"section": "77", "title": "Voyeurism",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "By its wording applies to women only. Covers watching, capturing, or disseminating image of a woman in a private act.",
             "gender_restriction": "female"},
        ],
        "it_act": [
            {"section": "66E", "title": "Violation of privacy",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "Covers capturing, publishing or transmitting image of private area without consent."},
            {"section": "67", "title": "Publishing obscene material in electronic form",
             "status": VerificationStatus.VERIFIED_SECONDARY},
            {"section": "67A", "title": "Publishing sexually explicit material in electronic form",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "evidence_needed": [
            "intimate content identification", "lack of consent evidence",
            "distribution evidence",
        ],
        "notes": "Whether 66E or BNS 77 reach synthetic imagery is unsettled. BNS 77 by its wording applies to women only.",
        "gender_restriction": None,  # varies by section; checked per-section
        "source_url": "",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "harassment_stalking",
        "label": "Harassment, stalking, defamation",
        "preconditions": {
            "harassment_pattern": True,
        },
        "bns": [
            {"section": "78", "title": "Stalking",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "By its wording: a man stalking a woman.",
             "gender_restriction": "female"},
            {"section": "356", "title": "Defamation",
             "status": VerificationStatus.UNVERIFIED},
            {"section": "351", "title": "Criminal intimidation",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "it_act": [
            {"section": "66", "title": "Computer-related offences",
             "status": VerificationStatus.VERIFIED_SECONDARY},
            {"section": "67", "title": "Publishing obscene material",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "evidence_needed": [
            "pattern of harassment", "communication records",
            "evidence of distress to victim",
        ],
        "notes": "",
        "gender_restriction": None,
        "source_url": "",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "minor_involved",
        "label": "Minor possibly involved",
        "preconditions": {
            "possible_minor": True,
        },
        "bns": [],
        "it_act": [
            {"section": "67B", "title": "Material depicting children in sexually explicit act",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "pocso": [
            {"act": "POCSO Act 2012", "status": VerificationStatus.UNVERIFIED,
             "note": "Specific provisions to be confirmed."},
        ],
        "evidence_needed": [
            "age verification", "victim identification",
        ],
        "notes": "ESCALATE IMMEDIATELY. Do not copy or further route the media.",
        "escalation_required": True,
        "gender_restriction": None,
        "source_url": "",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "syndicate_network",
        "label": "Syndicate or repeated network",
        "preconditions": {
            "network_indicators": True,
        },
        "bns": [
            {"section": "111", "title": "Organised crime",
             "status": VerificationStatus.UNVERIFIED,
             "note": "One secondary source says cyber-crimes fall within scope. Only the legal officer decides."},
            {"section": "112", "title": "Petty organised crime",
             "status": VerificationStatus.UNVERIFIED},
        ],
        "it_act": [],
        "evidence_needed": [
            "multiple victims", "shared identifiers", "financial network",
            "cross-case link evidence",
        ],
        "notes": "Only the legal officer decides whether organised crime provisions apply.",
        "gender_restriction": None,
        "source_url": "",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
    {
        "key": "electronic_evidence",
        "label": "Electronic evidence admissibility",
        "preconditions": {},  # Always applicable
        "bns": [],
        "it_act": [
            {"section": "79A", "title": "Examiner of electronic evidence",
             "status": VerificationStatus.VERIFIED_SECONDARY},
        ],
        "bsa": [
            {"section": "63", "title": "Admissibility of electronic records",
             "status": VerificationStatus.VERIFIED_SECONDARY,
             "note": "Section 63(4) requires certificate with hash value disclosure."},
        ],
        "evidence_needed": [
            "hash of electronic record", "device details",
            "certificate in Schedule format",
        ],
        "notes": "",
        "gender_restriction": None,
        "source_url": "https://www.livelaw.in/amp/top-stories/supreme-court-rejects-challenge-to-s634-bsa-mandating-hash-value-disclosure-for-electronic-evidence-535950",
        "verified_on": "2026-09-28",
        "verified_by": "pending legal officer",
    },
]


# ---------------------------------------------------------------------------
# Rule result
# ---------------------------------------------------------------------------

@dataclass
class RuleResult:
    """Result of evaluating one rule against case facts."""
    rule_id: str
    key: str
    label: str
    applicable: bool
    reason: str
    sections: list[dict] = field(default_factory=list)
    evidence_needed: list[str] = field(default_factory=list)
    gender_warnings: list[str] = field(default_factory=list)
    notes: str = ""
    escalation_required: bool = False
    verification_status: str = "pending"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rules Engine
# ---------------------------------------------------------------------------

class LegalRulesEngine:
    """
    Deterministic rules engine for legal section mapping.

    Usage:
        engine = LegalRulesEngine()
        case_facts = {
            "demand_made": True,
            "victim_gender": "male",
            "possible_minor": False,
            "intimate_content": True,
        }
        results = engine.evaluate("extortion", case_facts)
    """

    def __init__(self, rules: Optional[list[dict]] = None):
        self.rules = {r["key"]: r for r in (rules or RULES_TABLE)}
        self.version = RULES_TABLE_VERSION

    def get_rule(self, key: str) -> Optional[dict]:
        """Get a rule by its key."""
        return self.rules.get(key)

    def get_all_keys(self) -> list[str]:
        """Get all available circumstance keys."""
        return list(self.rules.keys())

    def get_all_section_ids(self) -> set[str]:
        """
        Get all valid section IDs (RULE-key format) for citation checking.
        The Verifier uses this to reject any section not in the table.
        """
        ids = set()
        for rule in self.rules.values():
            key = rule["key"]
            for act_key in ("bns", "it_act", "bsa", "pocso"):
                for section in rule.get(act_key, []):
                    sec_num = section.get("section", section.get("act", ""))
                    ids.add(f"RULE-{key}")
                    ids.add(f"RULE-{key}.{sec_num}")
        return ids

    def check_preconditions(
        self, rule: dict, case_facts: dict
    ) -> tuple[bool, str]:
        """
        Check whether a rule's preconditions are met by the case facts.

        Returns: (met, reason)
        """
        preconditions = rule.get("preconditions", {})

        # Empty preconditions = always applicable
        if not preconditions:
            return True, "No preconditions; always applicable"

        unmet = []
        for key, required_value in preconditions.items():
            actual = case_facts.get(key)
            if actual is None:
                unmet.append(f"'{key}' not provided in case facts")
            elif actual != required_value:
                unmet.append(
                    f"'{key}' is {actual}, required {required_value}"
                )

        if unmet:
            return False, f"Not applicable by its wording: {'; '.join(unmet)}"
        return True, "Preconditions met"

    def check_gender_restrictions(
        self, rule: dict, victim_gender: Optional[str]
    ) -> list[str]:
        """
        Check gender-specific provisions and generate warnings.

        Important: BNS 77 (voyeurism) and 78 (stalking) are worded for women
        victims only. For male victims, the engine must NOT propose them.
        """
        warnings = []

        for act_key in ("bns", "it_act", "bsa", "pocso"):
            for section in rule.get(act_key, []):
                restriction = section.get("gender_restriction")
                if restriction and victim_gender:
                    if victim_gender.lower() != restriction.lower():
                        sec_id = section.get("section", "?")
                        warnings.append(
                            f"Section {sec_id} ({section.get('title', '')}) is worded "
                            f"for {restriction} victims; victim gender is {victim_gender}. "
                            f"This section may not apply."
                        )

        return warnings

    def evaluate(
        self,
        circumstance_key: str,
        case_facts: dict,
    ) -> RuleResult:
        """
        Evaluate a single circumstance against case facts.

        Args:
            circumstance_key: key from the rules table (e.g., "extortion")
            case_facts: dict of case facts including victim_gender, etc.

        Returns:
            RuleResult with applicable sections and warnings.
        """
        rule = self.rules.get(circumstance_key)

        if rule is None:
            return RuleResult(
                rule_id=f"RULE-{circumstance_key}",
                key=circumstance_key,
                label=f"Unknown circumstance: {circumstance_key}",
                applicable=False,
                reason=f"Circumstance key '{circumstance_key}' not found in rules table (v{self.version})",
            )

        # Check preconditions
        met, reason = self.check_preconditions(rule, case_facts)

        # Check gender restrictions
        victim_gender = case_facts.get("victim_gender")
        gender_warnings = self.check_gender_restrictions(rule, victim_gender)

        # Collect sections (filtering out gender-restricted ones for wrong gender)
        sections = []
        for act_key in ("bns", "it_act", "bsa", "pocso"):
            for section in rule.get(act_key, []):
                sec_dict = {
                    "act": act_key.upper().replace("_", " "),
                    "section": section.get("section", section.get("act", "")),
                    "title": section.get("title", ""),
                    "status": section.get("status", VerificationStatus.UNVERIFIED),
                    "note": section.get("note", ""),
                }

                # Mark gender-restricted sections
                restriction = section.get("gender_restriction")
                if restriction and victim_gender:
                    if victim_gender.lower() != restriction.lower():
                        sec_dict["excluded"] = True
                        sec_dict["exclusion_reason"] = (
                            f"Worded for {restriction} victims; "
                            f"victim is {victim_gender}"
                        )
                    else:
                        sec_dict["excluded"] = False
                else:
                    sec_dict["excluded"] = False

                sections.append(sec_dict)

        return RuleResult(
            rule_id=f"RULE-{circumstance_key}",
            key=circumstance_key,
            label=rule["label"],
            applicable=met,
            reason=reason,
            sections=sections,
            evidence_needed=rule.get("evidence_needed", []),
            gender_warnings=gender_warnings,
            notes=rule.get("notes", ""),
            escalation_required=rule.get("escalation_required", False),
        )

    def evaluate_multiple(
        self,
        circumstance_keys: list[str],
        case_facts: dict,
    ) -> list[RuleResult]:
        """Evaluate multiple circumstances."""
        return [
            self.evaluate(key, case_facts)
            for key in circumstance_keys
        ]

    def evaluate_all(self, case_facts: dict) -> list[RuleResult]:
        """Evaluate all rules in the table against case facts."""
        return self.evaluate_multiple(list(self.rules.keys()), case_facts)

    def export_table(self) -> dict:
        """Export the rules table for transparency and verification."""
        return {
            "version": self.version,
            "rules_count": len(self.rules),
            "rules": [
                {
                    "key": r["key"],
                    "label": r["label"],
                    "preconditions": r.get("preconditions", {}),
                    "section_count": sum(
                        len(r.get(ak, []))
                        for ak in ("bns", "it_act", "bsa", "pocso")
                    ),
                    "verified_on": r.get("verified_on", ""),
                    "verified_by": r.get("verified_by", ""),
                }
                for r in self.rules.values()
            ],
            "disclaimer": (
                "This table is decision support, not legal advice. "
                "Every row requires legal-officer confirmation. "
                "Status 'verified_secondary' means wording was seen on a secondary source, "
                "not on India Code. The system never states that a person should be charged."
            ),
        }
