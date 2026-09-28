"""
EMAFIG Plane C — Module 3: Custody Log

Records who held evidence, when, why, and transfers between people.
This fills the "chain of custody" section required by BSA Section 63(4)
and general forensic practice.

Every custody event is also recorded in the hash-chained ledger for
tamper-evidence, but this module provides the domain-specific view.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Custody event types
# ---------------------------------------------------------------------------

CUSTODY_EVENTS = frozenset({
    "seized",       # initial seizure from a device or platform
    "received",     # received from another person or organization
    "transferred",  # handed to another person
    "accessed",     # opened / examined (non-transfer)
    "stored",       # placed in storage (e.g., locker, encrypted drive)
    "returned",     # returned to owner
    "disposed",     # destroyed per policy
    "exported",     # exported as part of a report package
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CustodyEvent:
    """A single custody event for a piece of evidence."""
    event_id: str
    case_id: str
    evidence_id: str
    event_type: str            # one of CUSTODY_EVENTS
    timestamp: str             # ISO 8601 UTC
    actor_id: str              # person or system ID
    actor_name: str
    actor_role: str            # "first_responder" | "analyst" | "supervisor" | "system"
    location: Optional[str] = None
    from_actor: Optional[str] = None   # for transfers: who handed it over
    to_actor: Optional[str] = None     # for transfers: who received it
    reason: Optional[str] = None
    seizure_memo_ref: Optional[str] = None
    device_make: Optional[str] = None
    device_model: Optional[str] = None
    device_serial: Optional[str] = None
    device_imei: Optional[str] = None
    storage_medium: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Custody Log
# ---------------------------------------------------------------------------

class CustodyLog:
    """
    Append-only custody log stored as JSONL.

    Usage:
        log = CustodyLog("cases/CASE-2026-001/custody.jsonl")
        event = log.record_seizure(
            case_id="CASE-2026-001",
            evidence_id="EVD-001",
            actor_id="OFF-101",
            actor_name="SI Sharma",
            actor_role="first_responder",
            seizure_memo_ref="SM/2026/CYB/001",
            device_make="Samsung",
            device_model="Galaxy A54",
        )
        chain = log.chain_for("EVD-001")
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _append(self, event: CustodyEvent) -> CustodyEvent:
        """Append a custody event to the log file."""
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def _make_event(
        self,
        event_type: str,
        case_id: str,
        evidence_id: str,
        actor_id: str,
        actor_name: str,
        actor_role: str,
        **kwargs,
    ) -> CustodyEvent:
        """Create and validate a custody event."""
        if event_type not in CUSTODY_EVENTS:
            raise ValueError(
                f"Invalid custody event type '{event_type}'. "
                f"Must be one of: {', '.join(sorted(CUSTODY_EVENTS))}"
            )
        return CustodyEvent(
            event_id=f"CUS-{uuid.uuid4().hex[:8].upper()}",
            case_id=case_id,
            evidence_id=evidence_id,
            event_type=event_type,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            **kwargs,
        )

    # ---- convenience methods ---------------------------------------------

    def record_seizure(
        self,
        case_id: str,
        evidence_id: str,
        actor_id: str,
        actor_name: str,
        actor_role: str = "first_responder",
        **kwargs,
    ) -> CustodyEvent:
        """Record that evidence was seized from a device or location."""
        event = self._make_event(
            "seized", case_id, evidence_id,
            actor_id, actor_name, actor_role, **kwargs,
        )
        return self._append(event)

    def record_received(
        self,
        case_id: str,
        evidence_id: str,
        actor_id: str,
        actor_name: str,
        from_actor: str,
        actor_role: str = "analyst",
        **kwargs,
    ) -> CustodyEvent:
        """Record that evidence was received from another person/org."""
        event = self._make_event(
            "received", case_id, evidence_id,
            actor_id, actor_name, actor_role,
            from_actor=from_actor, **kwargs,
        )
        return self._append(event)

    def record_transfer(
        self,
        case_id: str,
        evidence_id: str,
        from_actor_id: str,
        from_actor_name: str,
        to_actor_id: str,
        to_actor_name: str,
        reason: Optional[str] = None,
        **kwargs,
    ) -> CustodyEvent:
        """Record a transfer of custody between two people."""
        event = self._make_event(
            "transferred", case_id, evidence_id,
            from_actor_id, from_actor_name, "analyst",
            from_actor=from_actor_name,
            to_actor=to_actor_name,
            reason=reason,
            **kwargs,
        )
        return self._append(event)

    def record_access(
        self,
        case_id: str,
        evidence_id: str,
        actor_id: str,
        actor_name: str,
        reason: str,
        actor_role: str = "analyst",
        **kwargs,
    ) -> CustodyEvent:
        """Record that evidence was accessed/examined."""
        event = self._make_event(
            "accessed", case_id, evidence_id,
            actor_id, actor_name, actor_role,
            reason=reason, **kwargs,
        )
        return self._append(event)

    def record_stored(
        self,
        case_id: str,
        evidence_id: str,
        actor_id: str,
        actor_name: str,
        location: str,
        storage_medium: Optional[str] = None,
        **kwargs,
    ) -> CustodyEvent:
        """Record that evidence was placed in storage."""
        event = self._make_event(
            "stored", case_id, evidence_id,
            actor_id, actor_name, "system",
            location=location,
            storage_medium=storage_medium,
            **kwargs,
        )
        return self._append(event)

    def record_export(
        self,
        case_id: str,
        evidence_id: str,
        actor_id: str,
        actor_name: str,
        reason: str = "Report package export",
        **kwargs,
    ) -> CustodyEvent:
        """Record that evidence was exported as part of a package."""
        event = self._make_event(
            "exported", case_id, evidence_id,
            actor_id, actor_name, "analyst",
            reason=reason, **kwargs,
        )
        return self._append(event)

    # ---- query methods ---------------------------------------------------

    def all_events(self) -> list[CustodyEvent]:
        """Read all custody events."""
        events = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    d = json.loads(stripped)
                    events.append(CustodyEvent(**d))
        return events

    def chain_for(self, evidence_id: str) -> list[CustodyEvent]:
        """Get the full custody chain for a specific piece of evidence, in order."""
        return [e for e in self.all_events() if e.evidence_id == evidence_id]

    def current_holder(self, evidence_id: str) -> Optional[str]:
        """Determine who currently holds a piece of evidence."""
        chain = self.chain_for(evidence_id)
        if not chain:
            return None

        last = chain[-1]
        if last.event_type == "transferred" and last.to_actor:
            return last.to_actor
        return last.actor_name

    def to_report_section(self, evidence_id: str) -> list[dict]:
        """
        Format custody chain for inclusion in a report/certificate.
        Returns a list of dicts suitable for rendering.
        """
        chain = self.chain_for(evidence_id)
        return [
            {
                "timestamp": e.timestamp,
                "event": e.event_type,
                "person": e.actor_name,
                "role": e.actor_role,
                "from": e.from_actor,
                "to": e.to_actor,
                "location": e.location,
                "reason": e.reason,
                "seizure_memo": e.seizure_memo_ref,
            }
            for e in chain
        ]
