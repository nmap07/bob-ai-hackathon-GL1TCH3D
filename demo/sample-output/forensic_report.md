# EMAFIG Forensic Investigation — CASE-20260928T094939-3e3508a6bae8

## Executive status
- Media: `demo_clip.mp4` (video)
- SHA-256: `ab5a55f617899289e5cfd23f37b9958366c6284542e309f5bac73f13bf30ea89`
- SHA-512: `19034ae61ede66203e1794c1be16eab2ce544cac81e8cd73a47716cd986dc7e75d010d25402659e4e8a347a0e20b46361983f03d096831fa912784779d2e9372`
- Automated status: `awaiting_review`

## Agent coverage

- **metadata-analysis** — completed_with_warnings — 12 observations
- **compression-analysis** — completed — 1 observations
- **visual-forensics** — completed — 3 observations
- **audio-forensics** — completed_with_warnings — 1 observations
- **temporal-analysis** — completed — 1 observations
- **av-sync-analysis** — completed — 1 observations
- **c2pa-provenance** — completed_with_warnings — 1 observations

## Observations

### OBS-3f42e2abce41 — compression.sharpness_screen
Sampled frame sharpness using Laplacian variance; mean 910.14.
- Measurement: `{"mean_laplacian_variance": 910.1447085902297, "std": 10.908659509380957}`
- Alternatives: focus, resize, denoising, codec quantization, source-camera processing
- Calibrated: `False`

### OBS-ead334147888 — av_sync.stream_start_offset
Container-reported video/audio start-time difference is 0.00 ms.
- Measurement: `{"offset_ms": 0.0, "video_start_s": 0.0, "audio_start_s": 0.0}`
- Alternatives: container timestamps, muxing delay, VFR, decoder behavior
- Calibrated: `False`

### OBS-0821fe69a49a — provenance.c2pa_marker_screen
No C2PA-related byte markers were detected.
- Measurement: `{"marker_detected": false, "verified": false}`
- Alternatives: unsupported embedding, stripped metadata
- Calibrated: `False`

### OBS-9cbf5c474ded — temporal.cadence
Measured 150 video packet timestamps; median PTS interval 0.040000s.
- Measurement: `{"packet_count": 150, "median_interval_s": 0.040000000000000036, "anomaly_count": 0, "anomaly_indices": []}`
- Alternatives: variable frame rate, container timestamp behavior, transcoding
- Calibrated: `False`

### OBS-51dbfb5844c1 — metadata.container
container observed as 'mov,mp4,m4a,3gp,3g2,mj2'.
- Measurement: `{"value": "mov,mp4,m4a,3gp,3g2,mj2"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-15d0eefdc743 — metadata.duration_seconds
duration_seconds observed as '6.000000'.
- Measurement: `{"value": "6.000000"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-3fbd1281222c — metadata.format_tags
format_tags observed as {'major_brand': 'isom', 'minor_version': '512', 'compatible_brands': 'isomiso2avc1mp41', 'encoder': 'Lavf60.16.100'}.
- Measurement: `{"value": {"major_brand": "isom", "minor_version": "512", "compatible_brands": "isomiso2avc1mp41", "encoder": "Lavf60.16.100"}}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-7925817865fa — metadata.video_codec
video_codec observed as 'h264'.
- Measurement: `{"value": "h264"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-6de3a2ce9670 — metadata.resolution
resolution observed as [640, 360].
- Measurement: `{"value": [640, 360]}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-e32d1bfa91c2 — metadata.r_frame_rate
r_frame_rate observed as '25/1'.
- Measurement: `{"value": "25/1"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-25bf062ee141 — metadata.avg_frame_rate
avg_frame_rate observed as '25/1'.
- Measurement: `{"value": "25/1"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-9b98ea4a3378 — metadata.audio_codec
audio_codec observed as 'aac'.
- Measurement: `{"value": "aac"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-ae0093c308ff — metadata.audio_sample_rate
audio_sample_rate observed as '44100'.
- Measurement: `{"value": "44100"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-9766f84ae88d — metadata.audio_channels
audio_channels observed as 1.
- Measurement: `{"value": 1}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-751fa257b4cf — metadata.stream_count
stream_count observed as 2.
- Measurement: `{"value": 2}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-57fe6b4a13a7 — metadata.encoder
encoder observed as 'Lavc60.31.102 libx264'.
- Measurement: `{"value": "Lavc60.31.102 libx264"}`
- Alternatives: none recorded
- Calibrated: `True`

### OBS-5d28b84bf498 — audio.spectral_profile
Audio decoded at 16000 Hz; 3 spectral-flux spikes exceeded the 3-sigma screening threshold.
- Measurement: `{"duration_s": 6.014, "sample_rate": 16000, "rms_mean": 0.08796395361423492, "rms_std": 0.002539644483476877, "spectral_centroid_mean": 448.3347550372671, "spectral_flux_spikes": 3, "spike_indices": [0, 1, 186]}`
- Alternatives: speech consonants, background events, editing boundaries, codec behavior
- Calibrated: `False`

### OBS-50ccead0f930 — visual.video_frame_sample
Extracted 32 frames from video for visual analysis.
- Measurement: `{"frames_sampled": 32, "first_frame_idx": 0, "last_frame_idx": 124, "first_ts_s": 0.0, "last_ts_s": 4.96}`
- Alternatives: none recorded
- Calibrated: `False`

### OBS-bd12c620908e — visual.face_detection
Detected 0 face instance(s) across 32 sampled frame(s).
- Measurement: `{"frames_examined": 32, "faces_detected": 0, "face_detection_rate": 0.0, "cascade_available": true}`
- Alternatives: occlusion, extreme pose, low resolution, non-human subjects, mask/glasses
- Calibrated: `False`

### OBS-9ba85281f9ef — visual.video_sharpness_profile
Frame sharpness (Laplacian variance): mean=833.75, std=75.49 across 32 sampled frames.
- Measurement: `{"mean_sharpness": 833.75, "std_sharpness": 75.485, "frame_count": 32}`
- Alternatives: motion blur, focus changes, transcoding, scene changes
- Calibrated: `False`

## Competing hypotheses

### H1 — Authentic recording
The submitted media is consistent with an authentic capture, subject to gaps and limitations.
- Supporting observations: none
- Contradicting observations: none

### H2 — Manipulated face/content
Some media content was altered after capture or generated synthetically.
- Supporting observations: OBS-5d28b84bf498
- Contradicting observations: none

### H3 — Fully synthetic/generated media
The media was generated or substantially synthesized rather than captured as presented.
- Supporting observations: OBS-5d28b84bf498
- Contradicting observations: none

### H4 — Authentic media with benign post-processing
Observed anomalies are explained by legitimate editing, resizing, transcoding or platform processing.
- Supporting observations: none
- Contradicting observations: none

### H5 — Manipulated content subsequently re-encoded
Manipulation may have been followed by ordinary transcoding or redistribution processing.
- Supporting observations: OBS-5d28b84bf498
- Contradicting observations: none

## Contradictions

- None recorded.

## Evidence gaps

- **metadata-analysis** — warnings: ['ExifTool not installed; detailed EXIF/XMP/IPTC metadata not extracted.']
- **audio-forensics** — warnings: ['AASIST model not installed. Place aasist.onnx under models/audio or set AASIST_MODEL.']
- **c2pa-provenance** — warnings: ['c2patool unavailable; provenance was not cryptographically verified.']

## Legal / evidence packaging
Legal references are candidates only and require human legal review.
The evidence package preserves hashes, tool/agent status, observations and audit-chain state.

## Limitations
- Automated screening is not a binary truth detector.
- Model scores are not probabilities unless a validated operating point and population are supplied.
- C2PA absence is a provenance gap, not proof of manipulation.
- Legal mapping is advisory and requires qualified human review.