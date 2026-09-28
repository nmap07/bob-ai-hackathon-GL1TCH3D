"""
EMAFIG Plane C — Module 9: BSA 2023 Section 63(4) Certificate Generator

Pre-fills the Bharatiya Sakshya Adhiniyam 2023 Section 63(4) certificate
in two parts:

  Part A: Device/source details, hash algorithm (SHA-256), hash value,
          list of electronic records, taken from the case record and ledger.

  Part B: Technical facts an expert would need — tools and versions,
          hash verification result, ledger head. Signature blocks LEFT BLANK.

What this tool does:
  - Pre-fills Part A from the case record
  - Pre-fills technical facts for Part B
  - Leaves BOTH signature blocks empty
  - Never signs, never claims to be the expert
  - Never expresses the expert opinion

What this tool does NOT do:
  - Sign the certificate
  - Act as the Section 79A-notified examiner
  - Express any expert opinion about authenticity
  - Replace the legal officer's check against the Schedule text

The legal officer MUST check the template against the BSA Schedule format
before use in court.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Certificate data structures
# ---------------------------------------------------------------------------

@dataclass
class PartA:
    """
    BSA 63(4) Part A — Device and electronic record details.
    Pre-filled from the case record.
    """
    # Source identification
    source_type: str = ""  # "mobile device", "computer", "server", "cloud platform", etc.
    device_make: Optional[str] = None
    device_model: Optional[str] = None
    device_serial_or_identifier: Optional[str] = None
    device_imei: Optional[str] = None
    operating_system: Optional[str] = None

    # Source details (for non-device sources)
    platform_name: Optional[str] = None
    platform_url: Optional[str] = None
    account_identifier: Optional[str] = None

    # Electronic record identification
    record_description: str = ""
    original_filename: Optional[str] = None
    file_format: Optional[str] = None
    file_size_bytes: Optional[int] = None
    acquisition_date: Optional[str] = None
    acquisition_method: Optional[str] = None

    # Hash disclosure (required by Section 63(4))
    hash_algorithm: str = "SHA-256"
    hash_value: str = ""

    # List of records
    records_list: list[dict] = field(default_factory=list)

    # Custody
    seized_by: Optional[str] = None
    seizure_memo_ref: Optional[str] = None
    chain_of_custody_summary: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PartB:
    """
    BSA 63(4) Part B — Expert certification facts.
    Pre-filled with technical facts; signature blocks LEFT BLANK.
    """
    # Technical facts for the expert
    tools_and_versions: list[dict] = field(default_factory=list)
    hash_verification_result: Optional[str] = None
    hash_verified_at: Optional[str] = None
    ledger_head: Optional[str] = None
    ledger_entries_count: int = 0
    ledger_chain_verified: bool = False
    analysis_summary: Optional[str] = None

    # Derivative records
    derivatives: list[dict] = field(default_factory=list)

    # Signature blocks — ALWAYS BLANK
    expert_name: str = ""  # BLANK — to be filled by the signing expert
    expert_designation: str = ""  # BLANK
    expert_qualification: str = ""  # BLANK
    expert_signature: str = ""  # BLANK
    expert_date: str = ""  # BLANK

    # Second signatory
    certifying_officer_name: str = ""  # BLANK
    certifying_officer_designation: str = ""  # BLANK
    certifying_officer_signature: str = ""  # BLANK
    certifying_officer_date: str = ""  # BLANK

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Certificate:
    """Complete BSA 63(4) certificate draft."""
    case_id: str
    evidence_id: str
    generated_at: str
    generator_version: str = "0.1.0"
    part_a: PartA = field(default_factory=PartA)
    part_b: PartB = field(default_factory=PartB)
    disclaimers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "evidence_id": self.evidence_id,
            "generated_at": self.generated_at,
            "generator_version": self.generator_version,
            "part_a": self.part_a.to_dict(),
            "part_b": self.part_b.to_dict(),
            "disclaimers": self.disclaimers,
        }


# ---------------------------------------------------------------------------
# Certificate Generator
# ---------------------------------------------------------------------------

class CertificateGenerator:
    """
    Pre-fills BSA 2023 Section 63(4) certificate from case data.

    Usage:
        gen = CertificateGenerator()
        cert = gen.generate(
            case_id="CASE-2026-001",
            evidence_record=evidence_record.to_dict(),
            custody_chain=custody_chain,
            ledger_summary=ledger.summary(),
            tool_runs=tool_runs,
        )
        cert_text = gen.render_text(cert)
    """

    VERSION = "0.1.0"

    STANDARD_DISCLAIMERS = [
        "This certificate is a DRAFT pre-filled by EMAFIG and requires review.",
        "All signature blocks are intentionally left blank.",
        "This tool does not sign, does not claim to be an expert, and does not "
        "express any expert opinion about the authenticity of the evidence.",
        "The legal officer must check this template against the BSA 2023 Schedule "
        "format before any use in proceedings.",
        "Admission of an electronic record under Section 63 is a separate question "
        "from the weight to be given to it.",
        "The hash value proves integrity of the stored copy, not authenticity of "
        "the original evidence.",
    ]

    def generate(
        self,
        case_id: str,
        evidence_record: dict,
        custody_chain: list[dict],
        ledger_summary: dict,
        tool_runs: Optional[list[dict]] = None,
        derivatives: Optional[list[dict]] = None,
    ) -> Certificate:
        """
        Generate a certificate draft from case data.

        Args:
            case_id: case identifier
            evidence_record: dict from EvidenceRecord.to_dict()
            custody_chain: list of custody events
            ledger_summary: dict from Ledger.summary()
            tool_runs: optional list of tool run results
            derivatives: optional list of derivative artifacts
        """
        artifact = evidence_record.get("artifact", {})
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # --- Build Part A ---
        part_a = PartA(
            source_type=self._infer_source_type(evidence_record),
            device_make=evidence_record.get("device_details", "").split("/")[0]
                if evidence_record.get("device_details") else None,
            device_model=evidence_record.get("device_details", "").split("/")[1]
                if evidence_record.get("device_details") and "/" in evidence_record.get("device_details", "")
                else None,
            platform_name=evidence_record.get("platform"),
            platform_url=evidence_record.get("source_url"),
            record_description=f"Electronic evidence {evidence_record.get('evidence_id', '')}",
            original_filename=artifact.get("file_name"),
            file_format=artifact.get("media_type"),
            file_size_bytes=artifact.get("size_bytes"),
            acquisition_date=artifact.get("created_at"),
            acquisition_method=evidence_record.get("how_received", "Digital submission"),
            hash_algorithm="SHA-256",
            hash_value=artifact.get("sha256", ""),
            seizure_memo_ref=evidence_record.get("seizure_memo_ref"),
        )

        # Build records list from ledger
        part_a.records_list = self._build_records_list(
            evidence_record, derivatives or []
        )

        # Custody summary
        if custody_chain:
            part_a.chain_of_custody_summary = self._summarize_custody(custody_chain)
            if custody_chain[0].get("person"):
                part_a.seized_by = custody_chain[0]["person"]

        # --- Build Part B ---
        part_b = PartB(
            tools_and_versions=self._collect_tools(tool_runs or []),
            hash_verification_result=(
                "VERIFIED — stored hash matches recomputed hash"
                if ledger_summary.get("chain_verified")
                else "VERIFICATION PENDING or FAILED"
            ),
            hash_verified_at=now,
            ledger_head=ledger_summary.get("ledger_head"),
            ledger_entries_count=ledger_summary.get("total_entries", 0),
            ledger_chain_verified=ledger_summary.get("chain_verified", False),
            derivatives=[
                {
                    "artifact_id": d.get("artifact_id", ""),
                    "description": d.get("file_name", ""),
                    "sha256": d.get("sha256", ""),
                    "derived_from": d.get("derived_from", ""),
                    "producer": d.get("producer", ""),
                }
                for d in (derivatives or [])
            ],
        )

        return Certificate(
            case_id=case_id,
            evidence_id=evidence_record.get("evidence_id", ""),
            generated_at=now,
            generator_version=self.VERSION,
            part_a=part_a,
            part_b=part_b,
            disclaimers=list(self.STANDARD_DISCLAIMERS),
        )

    def render_text(self, cert: Certificate) -> str:
        """
        Render the certificate as formatted text for review and printing.
        """
        lines = []
        lines.append("=" * 72)
        lines.append("CERTIFICATE UNDER SECTION 63(4)")
        lines.append("BHARATIYA SAKSHYA ADHINIYAM, 2023")
        lines.append("(DRAFT — PRE-FILLED BY EMAFIG — ALL SIGNATURES BLANK)")
        lines.append("=" * 72)
        lines.append("")

        lines.append(f"Case Reference:    {cert.case_id}")
        lines.append(f"Evidence Reference: {cert.evidence_id}")
        lines.append(f"Generated:          {cert.generated_at}")
        lines.append("")

        # Part A
        lines.append("-" * 72)
        lines.append("PART A — ELECTRONIC RECORD DETAILS")
        lines.append("-" * 72)
        lines.append("")

        pa = cert.part_a
        lines.append(f"1. Source Type:           {pa.source_type}")
        if pa.device_make:
            lines.append(f"   Device Make:           {pa.device_make}")
        if pa.device_model:
            lines.append(f"   Device Model:          {pa.device_model}")
        if pa.device_serial_or_identifier:
            lines.append(f"   Serial/Identifier:     {pa.device_serial_or_identifier}")
        if pa.device_imei:
            lines.append(f"   IMEI:                  {pa.device_imei}")
        if pa.platform_name:
            lines.append(f"   Platform:              {pa.platform_name}")
        if pa.platform_url:
            lines.append(f"   Source URL:             {pa.platform_url}")
        lines.append("")

        lines.append(f"2. Record Description:    {pa.record_description}")
        if pa.original_filename:
            lines.append(f"   Original Filename:     {pa.original_filename}")
        if pa.file_format:
            lines.append(f"   File Format:           {pa.file_format}")
        if pa.file_size_bytes:
            lines.append(f"   File Size:             {pa.file_size_bytes:,} bytes")
        if pa.acquisition_date:
            lines.append(f"   Acquired:              {pa.acquisition_date}")
        if pa.acquisition_method:
            lines.append(f"   Acquisition Method:    {pa.acquisition_method}")
        lines.append("")

        lines.append(f"3. Hash Value Disclosure (as required by Section 63(4)):")
        lines.append(f"   Algorithm:             {pa.hash_algorithm}")
        lines.append(f"   Hash Value:            {pa.hash_value}")
        lines.append("")

        if pa.records_list:
            lines.append("4. List of Electronic Records:")
            for i, rec in enumerate(pa.records_list, 1):
                lines.append(
                    f"   {i}. {rec.get('description', '')}  "
                    f"[SHA-256: {rec.get('sha256', '')[:16]}...]"
                )
            lines.append("")

        if pa.seizure_memo_ref:
            lines.append(f"5. Seizure Memo Reference: {pa.seizure_memo_ref}")
        if pa.chain_of_custody_summary:
            lines.append(f"6. Chain of Custody:      {pa.chain_of_custody_summary}")
        lines.append("")

        # Part B
        lines.append("-" * 72)
        lines.append("PART B — EXPERT CERTIFICATION")
        lines.append("-" * 72)
        lines.append("")

        pb = cert.part_b

        lines.append("1. Tools and Versions Used:")
        for tool in pb.tools_and_versions:
            lines.append(f"   - {tool.get('tool', '')}: {tool.get('version', '')}")
        lines.append("")

        lines.append(f"2. Hash Verification:     {pb.hash_verification_result}")
        lines.append(f"   Verified at:           {pb.hash_verified_at}")
        lines.append("")

        lines.append(f"3. Ledger Integrity:")
        lines.append(f"   Ledger Head:           {pb.ledger_head}")
        lines.append(f"   Total Entries:         {pb.ledger_entries_count}")
        lines.append(f"   Chain Verified:        {pb.ledger_chain_verified}")
        lines.append("")

        if pb.derivatives:
            lines.append("4. Derivative Records:")
            for d in pb.derivatives:
                lines.append(
                    f"   - {d.get('artifact_id', '')}: {d.get('description', '')} "
                    f"(from {d.get('derived_from', '')}, by {d.get('producer', '')})"
                )
            lines.append("")

        lines.append("5. Expert Certification:")
        lines.append("   [THE FOLLOWING SIGNATURE BLOCKS ARE INTENTIONALLY LEFT BLANK]")
        lines.append("")
        lines.append("   I, ______________________________ (Name),")
        lines.append("   Designation: ______________________________,")
        lines.append("   do hereby certify that the electronic record(s) described")
        lines.append("   in Part A were produced by the computer/device described")
        lines.append("   therein during the period of regular use, and that the")
        lines.append("   information contained therein is derived from information")
        lines.append("   fed into the computer/device in the ordinary course of")
        lines.append("   the activities described above.")
        lines.append("")
        lines.append("   Signature: ______________________________")
        lines.append("   Date:      ______________________________")
        lines.append("")
        lines.append("   Countersigned by:")
        lines.append("   Name:      ______________________________")
        lines.append("   Designation: ______________________________")
        lines.append("   Signature: ______________________________")
        lines.append("   Date:      ______________________________")
        lines.append("")

        # Disclaimers
        lines.append("-" * 72)
        lines.append("DISCLAIMERS")
        lines.append("-" * 72)
        for d in cert.disclaimers:
            lines.append(f"  • {d}")
        lines.append("")
        lines.append("=" * 72)
        lines.append(f"Generated by EMAFIG Certificate Generator v{cert.generator_version}")
        lines.append("=" * 72)

        return "\n".join(lines)

    def save(
        self, cert: Certificate, output_dir: str | Path
    ) -> tuple[Path, Path]:
        """
        Save the certificate as both JSON and text.
        Returns (json_path, text_path).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / f"certificate_{cert.evidence_id}.json"
        text_path = output_dir / f"certificate_{cert.evidence_id}.txt"

        json_path.write_text(
            json.dumps(cert.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        text_path.write_text(self.render_text(cert), encoding="utf-8")

        return json_path, text_path

    # ---- helpers ---------------------------------------------------------

    def _infer_source_type(self, evidence_record: dict) -> str:
        """Infer the source type from the evidence record."""
        how = (evidence_record.get("how_received") or "").lower()
        platform = (evidence_record.get("platform") or "").lower()

        if "usb" in how or "device" in how:
            return "Mobile device / storage media"
        if any(p in platform for p in ["whatsapp", "telegram", "signal"]):
            return f"Messaging platform ({evidence_record.get('platform', '')})"
        if any(p in platform for p in ["facebook", "instagram", "twitter", "youtube"]):
            return f"Social media platform ({evidence_record.get('platform', '')})"
        if "email" in how:
            return "Email"
        if "cloud" in how or "drive" in how:
            return "Cloud storage"
        return evidence_record.get("platform", "Digital source")

    def _build_records_list(
        self, evidence_record: dict, derivatives: list[dict]
    ) -> list[dict]:
        """Build the list of electronic records for Part A."""
        records = []

        # Original
        artifact = evidence_record.get("artifact", {})
        records.append({
            "description": f"Original evidence file: {artifact.get('file_name', '')}",
            "sha256": artifact.get("sha256", ""),
            "type": "original",
        })

        # Derivatives
        for d in derivatives:
            records.append({
                "description": f"Derivative: {d.get('file_name', '')} ({d.get('producer', '')})",
                "sha256": d.get("sha256", ""),
                "type": "derivative",
            })

        return records

    def _summarize_custody(self, custody_chain: list[dict]) -> str:
        """Summarize the custody chain for Part A."""
        events = []
        for e in custody_chain[:10]:  # cap for certificate brevity
            ts = e.get("timestamp", "")[:10]
            event = e.get("event", "")
            person = e.get("person", "")
            events.append(f"{ts}: {event} by {person}")
        return "; ".join(events)

    def _collect_tools(self, tool_runs: list[dict]) -> list[dict]:
        """Collect unique tools and their versions from tool runs."""
        seen = set()
        tools = []
        for tr in tool_runs:
            name = tr.get("tool_name", "")
            version = tr.get("tool_version", "unknown")
            key = f"{name}:{version}"
            if key not in seen:
                seen.add(key)
                tools.append({"tool": name, "version": version})
        return tools
