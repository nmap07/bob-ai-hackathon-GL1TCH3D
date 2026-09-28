"""
app/baselines.py
Built-in baseline profile, per-check baseline comparison, and the deterministic
risk index.

Every observation is compared with a baseline (a normal range or a category
rule) and receives:

    level   within | elevated | high | not_scored | insufficient_data
    points  0.0 .. 1.0   (within=0, elevated=0.5, high=1.0 unless a check says otherwise)

The risk index aggregates *independence groups*, not observations: the
strongest check in a group counts once, so correlated detectors on the same
pixels cannot inflate the score (plan §7.3).

    risk = 1 - PRODUCT over groups (1 - family_weight * group_points)
    risk_score = round(100 * risk)

IMPORTANT: every range below is a hand-set heuristic default. None is
calibrated on a labelled reference population, so the risk index is an
uncalibrated triage indicator, not a probability of manipulation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

PROFILE_ID = "builtin-default"
PROFILE_VERSION = "2026-09-28.1"
PROFILE_SOURCE = ("Hand-set heuristic default shipped with EMAFIG; not calibrated on a labelled "
                  "reference set of genuine and manipulated media.")

LEVEL_POINTS = {"within": 0.0, "elevated": 0.5, "high": 1.0}

# Maximum contribution of each evidence family to the risk index (0..1).
# Low weights where benign pipelines commonly produce the signal.
FAMILY_WEIGHTS: dict[str, float] = {
    "face_boundary": 0.45,
    "provenance": 0.60,
    "metadata_software": 0.35,
    "av_sync": 0.30,
    "temporal": 0.30,
    "audio_splice": 0.25,
    "frequency": 0.25,
    "recompression": 0.15,
    "sharpness": 0.10,
    "audio_model": 0.0,          # no validated operating point in the built-in profile
    "metadata_presence": 0.0,    # absence is not evidence (plan principle 11)
    "metadata_descriptive": 0.0,
    "visual_descriptive": 0.0,
    "officer_observation": 0.0,
}

# Hypotheses a flagged check is consistent with (feeds Observation.supports and the ACH fallback).
FAMILY_SUPPORTS: dict[str, list[str]] = {
    "face_boundary": ["H2", "H3", "H5"],
    "av_sync": ["H2", "H5", "H6", "H7"],
    "temporal": ["H2", "H5", "H7"],
    "audio_splice": ["H2", "H5", "H6"],
    "frequency": ["H2", "H3"],
    "recompression": ["H4", "H5", "H7"],
    "sharpness": ["H2", "H4"],
    "metadata_software": ["H2", "H4", "H5"],
    "provenance": ["H3"],
}


@dataclass
class Check:
    check_id: str
    obs_types: tuple[str, ...]
    metric: str
    unit: str
    kind: str                         # above | below | outside | category | not_scored
    extract: Callable[[dict], Any] = lambda m: None
    normal: tuple[float, float] | None = None   # inclusive normal range
    high: tuple[float, float] | None = None     # beyond this -> high (outside kind); for above/below use (thr, thr)
    min_support: Callable[[dict], tuple[bool, str]] | None = None
    categorise: Callable[[Any], tuple[str, float, str, list[str] | None]] | None = None
    rationale: str = ""
    reference: str = ""
    media: tuple[str, ...] = ("image", "video", "audio")

    def describe(self) -> dict:
        return {"check_id": self.check_id, "observation_types": list(self.obs_types), "metric": self.metric,
                "unit": self.unit, "kind": self.kind, "normal": self.normal, "high": self.high,
                "rationale": self.rationale, "reference": self.reference}


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ratio(num_key: str, den_key: str):
    def f(m):
        n, d = _num(m.get(num_key)), _num(m.get(den_key))
        return None if n is None or not d else n / d
    return f


def _at_least(key: str, minimum: float, what: str):
    def f(m):
        v = _num(m.get(key))
        if v is None or v < minimum:
            return False, f"insufficient data: {what} {v} < {minimum}"
        return True, ""
    return f


# --- category rules ---------------------------------------------------------
_GENERATORS = re.compile(
    r"\b(stable[\s-]?diffusion|midjourney|dall[\s·-]?e|firefly|deepfacelab|faceswap|facefusion|roop|reface|"
    r"sora|runway(ml)?|pika|kling|synthesia|heygen|d-id|elevenlabs|comfyui|automatic1111|novelai|"
    r"leonardo\.?ai|imagen|black forest labs|faceapp)\b", re.I)
_EDITORS = re.compile(
    r"\b(photoshop|lightroom|gimp|premiere|after effects|final cut|davinci|capcut|inshot|kinemaster|"
    r"filmora|snapseed|picsart|facetune|canva|imovie|vn video editor|pixelmator|affinity)\b", re.I)
_TRANSCODERS = re.compile(r"\b(lavf|lavc|handbrake|x264|x265|libx264|libx265|ffmpeg)\b", re.I)


def _software_category(values):
    text = " ".join(values if isinstance(values, list) else [str(values)])
    if _GENERATORS.search(text):
        return "high", 1.0, f"generative-AI tool named in tag: {_GENERATORS.search(text).group(0)}", ["H3", "H2"]
    if _EDITORS.search(text):
        return "elevated", 0.5, f"editing application named in tag: {_EDITORS.search(text).group(0)}", ["H2", "H4", "H5"]
    if _TRANSCODERS.search(text):
        return "elevated", 0.2, f"transcoder named in tag: {_TRANSCODERS.search(text).group(0)} (re-encoding, common on platforms)", ["H4", "H5"]
    return "within", 0.0, "no editing or generation tool named", []


def _c2pa_category(m):
    if not m.get("manifest_present"):
        return "not_scored", 0.0, "no manifest; absence of provenance is a gap, not evidence of manipulation", None
    if m.get("ai_generated_assertion"):
        return "high", 1.0, f"manifest declares AI/algorithmic source: {', '.join(m.get('ai_source_types') or [])}", ["H3"]
    if m.get("validation_failed"):
        return "elevated", 0.6, "manifest present but validation failed (possible tampering after signing)", ["H2", "H5"]
    return "within", 0.0, "valid manifest without AI-source declaration", []


def _resolution_category(m):
    n = int(m.get("distinct_resolutions") or 1)
    return ("elevated", 0.5, f"{n} distinct resolutions in one stream", ["H4", "H5", "H7"]) if n > 1 \
        else ("within", 0.0, "single resolution", [])


def _av_offset(m):
    v = _num(m.get("offset_ms"))
    return v


CHECKS: list[Check] = [
    Check("BL-VIS-01", ("visual.face_boundary_variation",), "face-boundary sharpness ratio, coefficient of variation",
          "ratio", "above", lambda m: _num(m.get("coefficient_of_variation", m.get("cv"))),
          normal=(0.0, 0.30), high=(0.60, 0.60),
          rationale="Blended face swaps tend to vary boundary sharpness between detections; stable capture varies little."),
    Check("BL-VIS-02", ("visual.face_boundary_screen",), "boundary/face Laplacian ratio", "ratio", "outside",
          lambda m: _num(m.get("boundary_face_ratio")), normal=(0.60, 1.60), high=(0.35, 2.50),
          rationale="A pasted face often has a sharper or softer edge than its interior."),
    Check("BL-VIS-03", ("visual.image_sharpness_screen", "compression.sharpness_screen"), "Laplacian variance",
          "variance", "below", lambda m: _num(m.get("laplacian_variance", m.get("mean_laplacian_variance"))),
          normal=(50.0, None), high=(15.0, 15.0),
          rationale="Very low detail can come from smoothing used to hide blending, but also from focus and resizing."),
    Check("BL-VIS-04", ("visual.video_sharpness_profile",), "frame sharpness coefficient of variation", "ratio",
          "above", _ratio("std_sharpness", "mean_sharpness"), normal=(0.0, 0.50), high=(1.00, 1.00),
          rationale="Large frame-to-frame sharpness swings can mark inserted or regenerated segments."),
    Check("BL-VIS-05", ("visual.frequency_screen",), "FFT high-frequency energy ratio", "ratio", "outside",
          lambda m: _num(m.get("fft_high_freq_ratio")), normal=(0.005, 0.12), high=(0.002, 0.25),
          rationale="Generator upsampling can leave excess or missing high-frequency energy."),
    Check("BL-VIS-06", ("visual.block_artifact_screen",), "8-px block boundary score", "ratio", "above",
          lambda m: _num(m.get("block_artifact_score")), normal=(0.0, 1.50), high=(2.50, 2.50),
          rationale="Strong block boundaries indicate heavy or repeated JPEG compression."),
    Check("BL-CMP-01", ("compression.ela_screen",), "ELA face/background ratio (block p99/p50 if no face)", "ratio",
          "outside",
          lambda m: _num(m.get("face_background_ela_ratio")) if m.get("face_background_ela_ratio") is not None
          else _num(m.get("ela_region_ratio")),
          normal=(0.50, 4.00), high=(0.33, 7.00),
          rationale="A region compressed at a different history shows a different error level; built-in sample WhatsApp JPEG measured ~2.3."),
    Check("BL-CMP-02", ("compression.gop_structure",), "irregular GOP fraction", "fraction", "above",
          lambda m: _num(m.get("gop_irregular_fraction")), normal=(0.0, 0.15), high=(0.40, 0.40),
          min_support=_at_least("gop_count", 3, "gop_count"),
          rationale="Cuts and re-encoding break a regular keyframe cadence; encoders also insert scene-cut keyframes."),
    Check("BL-CMP-03", ("compression.resolution_change",), "distinct resolutions in stream", "count", "category",
          categorise=lambda m: _resolution_category(m),
          rationale="Camera captures keep one resolution; concatenation and screen capture may not."),
    Check("BL-AUD-01", ("audio.spectral_profile",), "spectral-flux spikes per second (>3σ)", "1/s", "above",
          lambda m: _num(m.get("spikes_per_second")) if m.get("spikes_per_second") is not None
          else _ratio("spectral_flux_spikes", "duration_s")(m),
          normal=(0.0, 1.0), high=(2.5, 2.5), min_support=_at_least("duration_s", 3.0, "duration_s"),
          rationale="Splices and vocoder frame boundaries add abrupt spectral changes; consonants and noise also do."),
    Check("BL-AUD-02", ("audio.deepfake_model_signal",), "AASIST raw output", "logit", "not_scored",
          rationale="No validated operating point for AASIST on this population in the built-in profile."),
    Check("BL-TMP-01", ("temporal.cadence",), "PTS interval anomaly fraction", "fraction", "above",
          _ratio("anomaly_count", "packet_count"), normal=(0.0, 0.01), high=(0.05, 0.05),
          min_support=_at_least("packet_count", 30, "packet_count"),
          rationale="Dropped, duplicated or spliced frames disturb timestamp cadence; phones record variable frame rate."),
    Check("BL-AVS-01", ("av_sync.stream_start_offset",), "audio lead(+)/lag(-) at stream start", "ms", "outside",
          _av_offset, normal=(-125.0, 45.0), high=(-185.0, 90.0),
          rationale="Detectability thresholds +45 ms (audio early) / -125 ms (audio late); acceptability +90/-185 ms.",
          reference="ITU-R BT.1359-1"),
    Check("BL-MET-01", ("metadata.software_tag", "metadata.encoder"), "software/encoder tag", "category", "category",
          categorise=lambda m: _software_category(m.get("values", m.get("value", ""))),
          rationale="Tags naming generators or editors document processing history; tags can be forged or stripped."),
    Check("BL-PRV-01", ("provenance.c2pa",), "C2PA manifest state", "category", "category",
          categorise=_c2pa_category,
          rationale="Signed provenance declaring algorithmic media is strong; absence is not evidence."),
    Check("BL-PRV-02", ("provenance.c2pa_marker_screen",), "C2PA byte markers", "category", "not_scored",
          rationale="An unverified marker scan is not provenance."),
    Check("BL-MET-02", ("metadata.exif_absent", "metadata.exif"), "EXIF presence", "presence", "not_scored",
          rationale="Platforms strip EXIF by design; absence is non-diagnostic (plan principle 11)."),
]

_BY_TYPE: dict[str, Check] = {t: c for c in CHECKS for t in c.obs_types}


def _level_numeric(check: Check, v: float) -> tuple[str, float | None]:
    lo, hi = check.normal
    hlo, hhi = check.high
    if check.kind == "above":
        if v <= hi: return "within", 0.0
        return ("high" if v >= hhi else "elevated"), (v - hi) / max(abs(hi), 1e-9)
    if check.kind == "below":
        if v >= lo: return "within", 0.0
        return ("high" if v <= hlo else "elevated"), (lo - v) / max(abs(lo), 1e-9)
    # outside
    if lo <= v <= hi: return "within", 0.0
    span = max(hi - lo, 1e-9)
    dev = (lo - v) / span if v < lo else (v - hi) / span
    return ("high" if (v <= hlo or v >= hhi) else "elevated"), dev


def _fmt_range(check: Check) -> str | None:
    if check.kind == "above": return f"<= {check.normal[1]} (high >= {check.high[1]})"
    if check.kind == "below": return f">= {check.normal[0]} (high <= {check.high[0]})"
    if check.kind == "outside": return f"{check.normal[0]} .. {check.normal[1]} (high outside {check.high[0]} .. {check.high[1]})"
    return None


def assess(obs_type: str, measurement: dict, media_type: str, family: str) -> dict:
    """Compare one observation with the built-in baseline."""
    base = {"profile": PROFILE_ID, "profile_version": PROFILE_VERSION, "calibrated": False,
            "source": PROFILE_SOURCE, "family": family,
            "family_weight": FAMILY_WEIGHTS.get(family, 0.0)}
    check = _BY_TYPE.get(obs_type)
    if check is None:
        return {**base, "check_id": None, "level": "not_scored", "points": 0.0, "supports": [],
                "reason": "descriptive fact; no baseline applies"}
    base.update({"check_id": check.check_id, "metric": check.metric, "unit": check.unit,
                 "rationale": check.rationale, "reference": check.reference or None,
                 "normal_range": _fmt_range(check)})
    if check.kind == "not_scored":
        return {**base, "level": "not_scored", "points": 0.0, "supports": [], "reason": check.rationale}
    if check.kind == "category":
        level, points, reason, sup = check.categorise(measurement)
        return {**base, "level": level, "points": points, "reason": reason,
                "supports": sup if sup is not None else [],
                "value": measurement.get("values", measurement.get("value"))}
    if check.min_support:
        ok, why = check.min_support(measurement)
        if not ok:
            return {**base, "level": "insufficient_data", "points": 0.0, "supports": [], "reason": why}
    v = check.extract(measurement)
    if v is None:
        return {**base, "level": "insufficient_data", "points": 0.0, "supports": [],
                "reason": "metric not present in measurement"}
    level, dev = _level_numeric(check, v)
    return {**base, "value": round(v, 6), "level": level, "points": LEVEL_POINTS[level],
            "deviation": None if dev is None else round(dev, 4),
            "supports": FAMILY_SUPPORTS.get(family, []) if level != "within" else [],
            "reason": f"{check.metric} = {v:.4g}; baseline {_fmt_range(check)} -> {level}"}


def band(score: int) -> str:
    return "low" if score < 25 else ("moderate" if score < 60 else "high")


def compute_risk(observations: list[dict]) -> dict:
    """Aggregate baseline results into the uncalibrated 0-100 risk index.

    observations: dicts with observation_id, independence_group, review_status, baseline.
    Rejected observations are excluded.
    """
    groups: dict[str, dict] = {}
    counts = {"accepted": 0, "unreviewed": 0, "rejected": 0}
    for o in observations:
        counts[o.get("review_status", "unreviewed")] = counts.get(o.get("review_status", "unreviewed"), 0) + 1
        if o.get("review_status") == "rejected":
            continue
        b = o.get("baseline") or {}
        gid = o.get("independence_group") or o["observation_id"]
        g = groups.setdefault(gid, {"group_id": gid, "family": b.get("family"),
                                    "weight": b.get("family_weight", 0.0), "points": 0.0,
                                    "level": "within", "driver": None, "observations": []})
        g["observations"].append(o["observation_id"])
        if b.get("points", 0.0) > g["points"]:
            g.update(points=b["points"], level=b["level"], driver=o["observation_id"], reason=b.get("reason"))
    remaining = 1.0
    contributions = []
    for g in groups.values():
        c = g["weight"] * g["points"]
        remaining *= (1.0 - c)
        if c > 0:
            contributions.append({**g, "contribution": round(c, 4),
                                  "correlated_observations_counted_once": len(g["observations"])})
    score = int(round(100 * (1 - remaining)))
    contributions.sort(key=lambda x: -x["contribution"])
    return {
        "risk_score": score, "band": band(score), "scale": "0-100",
        "method": "noisy-OR over independence groups: 1 - Π(1 - family_weight × group_points); "
                  "strongest check per group counts once",
        "calibrated": False,
        "interpretation": "Uncalibrated triage index of how far measurements deviate from built-in baselines. "
                          "It is NOT a probability that the media is manipulated.",
        "profile": PROFILE_ID, "profile_version": PROFILE_VERSION,
        "groups_scored": len(groups), "contributions": contributions,
        "review_mix": counts,
    }


def profile_table() -> dict:
    return {"profile": PROFILE_ID, "version": PROFILE_VERSION, "source": PROFILE_SOURCE,
            "calibrated": False, "family_weights": FAMILY_WEIGHTS,
            "checks": [c.describe() for c in CHECKS]}
