"""
EMAFIG Plane C — Module 5: Independence Grouping

Groups observations that derive from the same derivative and the same feature
family. Corroboration counts groups, not observations: five detectors flagging
the same boundary region on the same derivative are one group, not five
independent lines of evidence.

This is critical for honest evidence assessment and for the ACH matrix.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Feature family mapping
# ---------------------------------------------------------------------------

# Maps observation types to their feature families.
# Observations from the same derivative_id AND the same family = one group.
FAMILY_MAP: dict[str, str] = {
    # Face boundary artifacts
    "face_boundary_artifact": "face_boundary",
    "blend_halo": "face_boundary",
    "jaw_warp": "face_boundary",
    "face_edge_anomaly": "face_boundary",
    "face_paste_indicator": "face_boundary",

    # Eye-related
    "blink_rate_low": "eyes",
    "blink_rate_high": "eyes",
    "catchlight_asymmetry": "eyes",
    "eye_gaze_inconsistency": "eyes",
    "pupil_shape_anomaly": "eyes",

    # Compression / recompression
    "double_compression": "recompression",
    "gop_irregularity": "recompression",
    "quality_mismatch": "recompression",
    "ela_anomaly": "recompression",
    "compression_artifact_mismatch": "recompression",

    # AV sync
    "av_sync_offset": "av_sync",
    "lip_sync_desync": "av_sync",
    "audio_video_drift": "av_sync",

    # Audio splice / manipulation
    "spectral_discontinuity": "audio_splice",
    "noise_floor_change": "audio_splice",
    "audio_splice_point": "audio_splice",
    "pitch_anomaly": "audio_splice",

    # Metadata presence / absence
    "metadata_stripped": "metadata_presence",
    "metadata_absent": "metadata_presence",
    "metadata_incomplete": "metadata_presence",
    "exif_missing": "metadata_presence",

    # Metadata content (software tags, etc.)
    "editing_software_tag": "metadata_software",
    "encoder_mismatch": "metadata_software",
    "creation_time_anomaly": "metadata_software",
    "software_version_suspicious": "metadata_software",

    # Temporal (P2)
    "frame_duplication": "temporal",
    "optical_flow_discontinuity": "temporal",
    "landmark_velocity_outlier": "temporal",

    # Provenance
    "c2pa_present": "provenance",
    "c2pa_absent": "provenance",
    "source_url_found": "provenance",
    "first_upload_identified": "provenance",

    # Facial features (general)
    "face_texture_anomaly": "face_texture",
    "skin_tone_inconsistency": "face_texture",
    "hair_boundary_artifact": "face_texture",

    # ---- Observation types emitted by the app/agents examiners ----
    # Descriptive facts: never diagnostic on their own.
    "visual.image_dimensions": "visual_descriptive",
    "visual.video_frame_sample": "visual_descriptive",
    "visual.face_detection": "visual_descriptive",
    # Same Laplacian-variance feature computed by two agents on the same
    # pixels: one line of evidence, not two.
    "visual.image_sharpness_screen": "sharpness",
    "visual.video_sharpness_profile": "sharpness",
    "compression.sharpness_screen": "sharpness",
    "visual.face_boundary_screen": "face_boundary",
    "visual.face_boundary_variation": "face_boundary",
    "visual.frequency_screen": "frequency",
    "visual.block_artifact_screen": "recompression",
    "compression.ela_screen": "recompression",
    "compression.gop_structure": "recompression",
    "compression.resolution_change": "recompression",
    "audio.spectral_profile": "audio_splice",
    "audio.deepfake_model_signal": "audio_model",
    "temporal.cadence": "temporal",
    "av_sync.stream_start_offset": "av_sync",
    "metadata.exif_absent": "metadata_presence",
    "metadata.exif": "metadata_presence",
    "metadata.encoder": "metadata_software",
    "metadata.software_tag": "metadata_software",
    "provenance.c2pa": "provenance",
    "provenance.c2pa_marker_screen": "provenance",
}

# Prefix fallbacks for type families not listed individually.
PREFIX_FAMILY: list[tuple[str, str]] = [
    ("metadata.", "metadata_descriptive"),
    ("provenance.", "provenance"),
    ("officer.", "officer_observation"),
]


# ---------------------------------------------------------------------------
# Grouping functions
# ---------------------------------------------------------------------------

def get_family(observation_type: str) -> str:
    """
    Get the feature family for an observation type.
    Falls back to the observation type itself if not in the mapping.
    """
    if observation_type in FAMILY_MAP:
        return FAMILY_MAP[observation_type]
    for prefix, family in PREFIX_FAMILY:
        if observation_type.startswith(prefix):
            return family
    return observation_type


def compute_group_id(observation: dict) -> str:
    """
    Compute the independence group ID for an observation.

    Format: "{derivative_id}:{family}"

    If no derivative_id is present, falls back to evidence_id.
    """
    derivative = observation.get("derivative_id") or observation.get("evidence_id", "UNKNOWN")
    family = get_family(observation.get("type", "unknown"))
    return f"{derivative}:{family}"


def group_observations(observations: list[dict]) -> dict[str, list[dict]]:
    """
    Group observations by independence.

    Args:
        observations: list of observation dicts (must have 'type' and
                      'derivative_id' or 'evidence_id')

    Returns:
        Dict mapping group_id -> list of observations in that group.
    """
    groups: dict[str, list[dict]] = {}
    for obs in observations:
        gid = compute_group_id(obs)
        # Store the group ID on the observation for reference
        obs["independence_group"] = gid
        if gid not in groups:
            groups[gid] = []
        groups[gid].append(obs)
    return groups


def count_corroborating_groups(
    observations: list[dict],
    filter_status: str = "confirmed",
) -> int:
    """
    Count how many independent groups have at least one confirmed observation.
    This is the correct measure of corroboration — not raw observation count.
    """
    filtered = [
        obs for obs in observations
        if obs.get("review", {}).get("status") == filter_status
    ]
    groups = group_observations(filtered)
    return len(groups)


def summarize_groups(observations: list[dict]) -> list[dict]:
    """
    Summarize independence groups for reporting and ACH input.

    Returns a list of group summaries, each with:
      - group_id
      - family
      - derivative_id
      - observation_count
      - observation_ids
      - observation_types
      - any_confirmed (whether at least one observation in the group is confirmed)
    """
    groups = group_observations(observations)
    summaries = []

    for gid, obs_list in groups.items():
        parts = gid.split(":", 1)
        derivative = parts[0] if parts else "UNKNOWN"
        family = parts[1] if len(parts) > 1 else "unknown"

        summaries.append({
            "group_id": gid,
            "family": family,
            "derivative_id": derivative,
            "observation_count": len(obs_list),
            "observation_ids": [o.get("obs_id", "?") for o in obs_list],
            "observation_types": list({o.get("type", "?") for o in obs_list}),
            "any_confirmed": any(
                o.get("review", {}).get("status") == "confirmed"
                for o in obs_list
            ),
            "all_rejected": all(
                o.get("review", {}).get("status") == "rejected"
                for o in obs_list
            ),
        })

    return summaries


def get_confirmed_groups(observations: list[dict]) -> list[dict]:
    """
    Get summaries of only those groups with at least one confirmed observation.
    These are the groups that feed into the ACH matrix.
    """
    return [
        g for g in summarize_groups(observations)
        if g["any_confirmed"] and not g["all_rejected"]
    ]
