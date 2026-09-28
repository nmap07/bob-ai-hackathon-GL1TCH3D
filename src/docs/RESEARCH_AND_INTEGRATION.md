# Research and integration decisions

## 1. Why this architecture
The supplied EMAFIG design explicitly rejects the simplistic "video -> classifier -> 94% fake" approach and instead uses evidence preservation, specialized agents, structured observations, cross-modal correlation, an evidence graph, competing hypotheses, adversarial verification and human review.

## 2. Visual/video detection
The implementation uses deterministic forensic screening by default and provides a clean adapter point for a calibrated deepfake model. This is intentional: current deepfake benchmarks show large generalization and post-processing challenges. DeepfakeBench provides a common benchmark framework with many image/video detectors and standardized metrics; it is therefore a better future model plug-in than inventing a single "best" detector.

For a model-backed deployment:
- install the selected DeepfakeBench detector in its own environment;
- expose a JSON adapter;
- record model version/hash and preprocessing;
- store raw score;
- calibrate threshold on the relevant validation population;
- never treat correlated model outputs as independent evidence.

## 3. Audio deepfake detection
AASIST was selected as the first model adapter because:
- it directly targets audio anti-spoofing;
- its published architecture models spectral and temporal artifacts;
- a maintained ONNX checkpoint is available;
- it has a small model footprint compared with large speech encoders.

ASVspoof 2021 includes a dedicated deepfake speech condition and diverse spoof attacks. This is a useful evaluation source, but operational media can differ substantially from challenge data.

## 4. Provenance
C2PA is integrated as provenance evidence. A missing credential is recorded as a gap, not as evidence of fakery. When `c2patool` or `c2pa-python` is available, the system can perform actual manifest validation.

## 5. Legal packaging
The legal layer is a candidate mapping and evidence-gap assistant. It is not a charging engine and never signs a certificate.

## 6. Evaluation
Create paired sets:
- authentic originals;
- face-swap / reenactment;
- lip-sync;
- voice conversion;
- synthetic speech;
- partial replacement;
- re-encoded manipulations;
- benign compression;
- resize/crop;
- frame-rate conversion;
- color correction;
- audio normalization;
- social-platform-like transcoding.

Report:
- detector metrics;
- localization accuracy;
- contradiction detection;
- alternative-explanation recall;
- missing-evidence recall;
- pipeline failure rate;
- reproducibility;
- time to investigation/report;
- unsupported-conclusion rate.

The key research contribution is not "AI detects deepfakes." It is the evidence-centric orchestration and traceability layer around multimodal detection.
