"""
EMAFIG Plane C — Module 10: Fingerprint Store + Cross-Case Linker

Cross-case linking based on cheap, deterministic signals:

  1. Reused source clips — perceptual hash of key frames, audio fingerprint
  2. Reused blackmail script — text similarity (MinHash) on chat exports
  3. Shared identifiers — HMAC of phone, UPI ID, URL, email with deployment secret
  4. Tool signature — encoder tags, codec parameters, container quirks

Design rules:
  - The fingerprint store holds hashes and features ONLY, never media.
  - Raw evidence stays in its own case folder.
  - Links are PROPOSED, never automatic; an officer approves each one.
  - Plain hashes of phone numbers are brute-forceable; HMAC with a deployment
    secret is used instead. The key stays with the authority.
  - Cross-district sharing needs an agreement (not implemented here).

Hackathon scope: 5–10 synthetic cases with two planted clusters; report
retrieval precision and recall on that set only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default deployment secret for HMAC (MUST be replaced in production)
DEFAULT_HMAC_SECRET = b"EMAFIG_DEV_SECRET_REPLACE_IN_PRODUCTION"

# Similarity thresholds
PHASH_THRESHOLD = 10       # Hamming distance <= 10 for perceptual hash match
MINHASH_THRESHOLD = 0.3    # Jaccard similarity >= 0.3 for text similarity
AUDIO_FP_THRESHOLD = 0.8   # Audio fingerprint correlation >= 0.8


# ---------------------------------------------------------------------------
# Perceptual hashing (simplified)
# ---------------------------------------------------------------------------

def compute_phash(image_path: str | Path, hash_size: int = 8) -> Optional[str]:
    """
    Compute a perceptual hash (pHash) of an image.
    Uses DCT-based hashing if OpenCV and numpy are available.
    Returns a hex string.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None

    # Resize to 32x32 for DCT (then take top-left hash_size x hash_size)
    resized = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
    resized = np.float32(resized)

    # Apply DCT
    dct = cv2.dct(resized)
    dct_low = dct[:hash_size, :hash_size]

    # Compute median
    median = np.median(dct_low)

    # Generate hash bits
    bits = (dct_low > median).flatten()
    hash_int = 0
    for bit in bits:
        hash_int = (hash_int << 1) | int(bit)

    return format(hash_int, f"0{hash_size * hash_size // 4}x")


def phash_distance(hash1: str, hash2: str) -> int:
    """Hamming distance between two hex hash strings."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return 999
    val1 = int(hash1, 16)
    val2 = int(hash2, 16)
    xor = val1 ^ val2
    return bin(xor).count("1")


# ---------------------------------------------------------------------------
# MinHash for text similarity
# ---------------------------------------------------------------------------

class MinHash:
    """
    MinHash for estimating Jaccard similarity between text documents.
    Used for detecting reused blackmail scripts in chat exports.
    """

    def __init__(self, num_perm: int = 128, seed: int = 42):
        self.num_perm = num_perm
        self.seed = seed
        # Generate hash function parameters
        import random
        rng = random.Random(seed)
        self._a = [rng.randint(1, 2**31 - 1) for _ in range(num_perm)]
        self._b = [rng.randint(0, 2**31 - 1) for _ in range(num_perm)]
        self._c = (1 << 31) - 1  # Mersenne prime

    def compute(self, text: str) -> list[int]:
        """Compute MinHash signature for a text."""
        # Tokenize into shingles (3-grams of words)
        words = text.lower().split()
        shingles = set()
        for i in range(len(words) - 2):
            shingle = " ".join(words[i:i+3])
            shingles.add(shingle)

        if not shingles:
            return [self._c] * self.num_perm

        # Compute MinHash
        signature = []
        for i in range(self.num_perm):
            min_hash = float("inf")
            for shingle in shingles:
                h = hash(shingle) & 0x7FFFFFFF
                val = (self._a[i] * h + self._b[i]) % self._c
                min_hash = min(min_hash, val)
            signature.append(min_hash)

        return signature

    @staticmethod
    def jaccard(sig1: list[int], sig2: list[int]) -> float:
        """Estimate Jaccard similarity from two MinHash signatures."""
        if len(sig1) != len(sig2):
            return 0.0
        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / len(sig1)


# ---------------------------------------------------------------------------
# HMAC-based identifier hashing
# ---------------------------------------------------------------------------

def hmac_identifier(identifier: str, secret: bytes = DEFAULT_HMAC_SECRET) -> str:
    """
    HMAC a sensitive identifier (phone, UPI ID, email) with the deployment secret.
    This prevents brute-force attacks on plain hashes.
    The key stays with the authority; cross-district sharing needs an agreement.
    """
    return hmac.new(
        secret,
        identifier.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Fingerprint record
# ---------------------------------------------------------------------------

@dataclass
class Fingerprint:
    """A single fingerprint entry in the store."""
    fingerprint_id: str
    case_ref: str
    evidence_ref: str
    signal_type: str  # "phash", "audio_fp", "text_minhash", "identifier", "tool_sig"
    value: str  # hash hex, HMAC hex, or JSON-encoded vector
    metadata: dict = field(default_factory=dict)  # e.g., {"encoder": "Lavf58.20.100"}
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LinkProposal:
    """A proposed link between two cases."""
    link_id: str
    case_a: str
    case_b: str
    signal_type: str
    similarity: float
    evidence_a: str
    evidence_b: str
    fingerprint_a: str
    fingerprint_b: str
    details: dict = field(default_factory=dict)
    status: str = "proposed"  # "proposed" | "approved" | "rejected"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Fingerprint Store
# ---------------------------------------------------------------------------

class FingerprintStore:
    """
    SQLite-backed fingerprint store (uses JSON file for hackathon simplicity).
    Stores hashes and features only, never media.

    Usage:
        store = FingerprintStore("fingerprints.json")
        store.add_phash("CASE-001", "EVD-001", phash_value)
        store.add_identifier("CASE-001", "EVD-001", "+91-9876543210", "phone")
        proposals = store.find_matches("CASE-002")
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fingerprints: list[Fingerprint] = []
        self._links: list[LinkProposal] = []
        self._load()

    def _load(self):
        """Load fingerprints from the JSON file."""
        if self.path.exists() and self.path.stat().st_size > 0:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._fingerprints = [
                Fingerprint(**fp) for fp in data.get("fingerprints", [])
            ]
            self._links = [
                LinkProposal(**lp) for lp in data.get("links", [])
            ]

    def _save(self):
        """Save fingerprints to the JSON file."""
        data = {
            "fingerprints": [fp.to_dict() for fp in self._fingerprints],
            "links": [lp.to_dict() for lp in self._links],
        }
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _gen_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

    # ---- Add fingerprints ------------------------------------------------

    def add_phash(
        self,
        case_ref: str,
        evidence_ref: str,
        phash_value: str,
        **metadata,
    ) -> Fingerprint:
        """Add a perceptual hash fingerprint for a keyframe."""
        fp = Fingerprint(
            fingerprint_id=self._gen_id("FP"),
            case_ref=case_ref,
            evidence_ref=evidence_ref,
            signal_type="phash",
            value=phash_value,
            metadata=metadata,
        )
        self._fingerprints.append(fp)
        self._save()
        return fp

    def add_audio_fingerprint(
        self,
        case_ref: str,
        evidence_ref: str,
        audio_hash: str,
        **metadata,
    ) -> Fingerprint:
        """Add an audio fingerprint."""
        fp = Fingerprint(
            fingerprint_id=self._gen_id("FP"),
            case_ref=case_ref,
            evidence_ref=evidence_ref,
            signal_type="audio_fp",
            value=audio_hash,
            metadata=metadata,
        )
        self._fingerprints.append(fp)
        self._save()
        return fp

    def add_text_minhash(
        self,
        case_ref: str,
        evidence_ref: str,
        minhash_signature: list[int],
        **metadata,
    ) -> Fingerprint:
        """Add a MinHash signature for a chat export / text."""
        fp = Fingerprint(
            fingerprint_id=self._gen_id("FP"),
            case_ref=case_ref,
            evidence_ref=evidence_ref,
            signal_type="text_minhash",
            value=json.dumps(minhash_signature),
            metadata=metadata,
        )
        self._fingerprints.append(fp)
        self._save()
        return fp

    def add_identifier(
        self,
        case_ref: str,
        evidence_ref: str,
        identifier: str,
        identifier_type: str,
        secret: bytes = DEFAULT_HMAC_SECRET,
    ) -> Fingerprint:
        """
        Add an HMAC'd identifier (phone, UPI ID, email, URL).
        The raw identifier is NEVER stored.
        """
        fp = Fingerprint(
            fingerprint_id=self._gen_id("FP"),
            case_ref=case_ref,
            evidence_ref=evidence_ref,
            signal_type="identifier",
            value=hmac_identifier(identifier, secret),
            metadata={"identifier_type": identifier_type},
        )
        self._fingerprints.append(fp)
        self._save()
        return fp

    def add_tool_signature(
        self,
        case_ref: str,
        evidence_ref: str,
        encoder: str,
        codec_params: dict,
    ) -> Fingerprint:
        """Add tool signature (encoder tags, codec parameters)."""
        sig_value = hashlib.sha256(
            json.dumps(
                {"encoder": encoder, **codec_params},
                sort_keys=True,
            ).encode()
        ).hexdigest()

        fp = Fingerprint(
            fingerprint_id=self._gen_id("FP"),
            case_ref=case_ref,
            evidence_ref=evidence_ref,
            signal_type="tool_sig",
            value=sig_value,
            metadata={"encoder": encoder, **codec_params},
        )
        self._fingerprints.append(fp)
        self._save()
        return fp

    # ---- Find matches ----------------------------------------------------

    def find_matches(
        self,
        case_ref: str,
        exclude_same_case: bool = True,
    ) -> list[LinkProposal]:
        """
        Find potential matches between a case's fingerprints and all others.

        Returns a list of LinkProposals (PROPOSALS — officer must approve).
        """
        # Get this case's fingerprints
        case_fps = [
            fp for fp in self._fingerprints
            if fp.case_ref == case_ref
        ]

        # Get all other fingerprints
        other_fps = [
            fp for fp in self._fingerprints
            if (not exclude_same_case or fp.case_ref != case_ref)
        ]

        proposals = []

        for cfp in case_fps:
            for ofp in other_fps:
                if cfp.signal_type != ofp.signal_type:
                    continue

                similarity = self._compute_similarity(cfp, ofp)
                if similarity is None:
                    continue

                threshold = self._get_threshold(cfp.signal_type)
                if similarity >= threshold:
                    proposal = LinkProposal(
                        link_id=self._gen_id("LNK"),
                        case_a=case_ref,
                        case_b=ofp.case_ref,
                        signal_type=cfp.signal_type,
                        similarity=round(similarity, 4),
                        evidence_a=cfp.evidence_ref,
                        evidence_b=ofp.evidence_ref,
                        fingerprint_a=cfp.fingerprint_id,
                        fingerprint_b=ofp.fingerprint_id,
                        details={
                            "signal_type_label": self._signal_label(cfp.signal_type),
                        },
                    )
                    proposals.append(proposal)

        return proposals

    def find_clusters(self) -> list[dict]:
        """
        Find clusters of linked cases using union-find.
        Returns a list of clusters, each with case_refs and the signals that link them.
        """
        # Build adjacency from approved links
        approved = [lp for lp in self._links if lp.status == "approved"]

        # Union-Find
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for lp in approved:
            union(lp.case_a, lp.case_b)

        # Group by root
        clusters_map: dict[str, list[str]] = {}
        for case in parent:
            root = find(case)
            if root not in clusters_map:
                clusters_map[root] = []
            clusters_map[root].append(case)

        # Build output
        clusters = []
        for root, cases in clusters_map.items():
            if len(cases) < 2:
                continue
            links_in_cluster = [
                lp.to_dict() for lp in approved
                if lp.case_a in cases and lp.case_b in cases
            ]
            clusters.append({
                "cluster_id": self._gen_id("CLU"),
                "cases": sorted(set(cases)),
                "size": len(set(cases)),
                "links": links_in_cluster,
            })

        return clusters

    # ---- Link management -------------------------------------------------

    def approve_link(self, link_id: str, officer_id: str) -> Optional[LinkProposal]:
        """Officer approves a proposed link."""
        for lp in self._links:
            if lp.link_id == link_id:
                lp.status = "approved"
                lp.reviewed_by = officer_id
                lp.reviewed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._save()
                return lp
        return None

    def reject_link(self, link_id: str, officer_id: str) -> Optional[LinkProposal]:
        """Officer rejects a proposed link."""
        for lp in self._links:
            if lp.link_id == link_id:
                lp.status = "rejected"
                lp.reviewed_by = officer_id
                lp.reviewed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._save()
                return lp
        return None

    def save_proposals(self, proposals: list[LinkProposal]):
        """Save link proposals to the store."""
        self._links.extend(proposals)
        self._save()

    # ---- Helpers ---------------------------------------------------------

    def _compute_similarity(
        self, fp1: Fingerprint, fp2: Fingerprint
    ) -> Optional[float]:
        """Compute similarity between two fingerprints of the same type."""
        if fp1.signal_type == "phash":
            dist = phash_distance(fp1.value, fp2.value)
            max_bits = len(fp1.value) * 4  # hex chars * 4 bits
            return 1.0 - (dist / max_bits) if max_bits > 0 else 0.0

        elif fp1.signal_type == "identifier":
            # Exact match for HMAC'd identifiers
            return 1.0 if fp1.value == fp2.value else 0.0

        elif fp1.signal_type == "tool_sig":
            # Exact match for tool signatures
            return 1.0 if fp1.value == fp2.value else 0.0

        elif fp1.signal_type == "text_minhash":
            try:
                sig1 = json.loads(fp1.value)
                sig2 = json.loads(fp2.value)
                return MinHash.jaccard(sig1, sig2)
            except (json.JSONDecodeError, TypeError):
                return None

        elif fp1.signal_type == "audio_fp":
            # Simplified: exact match (real implementation would use correlation)
            return 1.0 if fp1.value == fp2.value else 0.0

        return None

    def _get_threshold(self, signal_type: str) -> float:
        """Get the match threshold for a signal type."""
        thresholds = {
            "phash": 0.9,           # High similarity required
            "identifier": 1.0,      # Exact match
            "tool_sig": 1.0,        # Exact match (weak alone)
            "text_minhash": MINHASH_THRESHOLD,
            "audio_fp": AUDIO_FP_THRESHOLD,
        }
        return thresholds.get(signal_type, 0.9)

    def _signal_label(self, signal_type: str) -> str:
        """Human-readable label for a signal type."""
        labels = {
            "phash": "Reused source clip (perceptual hash)",
            "audio_fp": "Reused audio (audio fingerprint)",
            "text_minhash": "Reused blackmail script (text similarity)",
            "identifier": "Shared identifier (phone/UPI/email)",
            "tool_sig": "Matching tool signature (encoder/codec)",
        }
        return labels.get(signal_type, signal_type)

    # ---- Stats -----------------------------------------------------------

    def stats(self) -> dict:
        """Get fingerprint store statistics."""
        by_type: dict[str, int] = {}
        by_case: dict[str, int] = {}
        for fp in self._fingerprints:
            by_type[fp.signal_type] = by_type.get(fp.signal_type, 0) + 1
            by_case[fp.case_ref] = by_case.get(fp.case_ref, 0) + 1

        return {
            "total_fingerprints": len(self._fingerprints),
            "total_links": len(self._links),
            "approved_links": sum(1 for lp in self._links if lp.status == "approved"),
            "rejected_links": sum(1 for lp in self._links if lp.status == "rejected"),
            "pending_links": sum(1 for lp in self._links if lp.status == "proposed"),
            "fingerprints_by_type": by_type,
            "fingerprints_by_case": by_case,
            "unique_cases": len(by_case),
        }
