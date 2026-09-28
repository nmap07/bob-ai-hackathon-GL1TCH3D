---
name: audio-deepfake-model
description: Use AASIST as an optional speech anti-spoofing signal while preserving raw score semantics and forensic limitations.
user-invocable: true
---

# Audio Deepfake Model

Use AASIST only as one evidence channel.

Input:
- extracted mono 16 kHz WAV
- fixed deterministic 64,600-sample window
- AASIST ONNX model

Output:
- raw model output
- model/version/hash
- input artifact hash
- no automatic probability unless a validated operating point is configured.

The model's published interface reports a score where higher means more bona-fide speech. Cross-dataset performance varies materially, so domain shift and codec/channel effects must be disclosed.

Always combine model evidence with spectral discontinuity, provenance, metadata and other independent evidence.
