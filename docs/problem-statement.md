# Problem Statement

## Who is affected
- **Investigators and prosecutors** who receive suspected synthetic or manipulated video, image or audio and must decide what it can support.
- **Forensic examiners** who have to justify measurements and methods, and who are cross-examined on them.
- **Courts and defence teams** who need to test whether a finding is reproducible and whether alternative explanations were considered.
- **Victims** of deepfake abuse whose cases stall when evidence cannot be presented credibly.

## Why existing solutions fall short
1. **A single score is not evidence.** A "97% fake" output has no location, no method a third party can repeat, and no account of what else could explain it.
2. **Post-processing looks like manipulation.** Resizing, re-encoding, platform transcoding and audio normalisation change the same signals detectors rely on. Deepfake benchmarks consistently report generalisation and post-processing problems.
3. **Correlated detectors are double counted.** Five detectors that look at the same frames are one observation, not five independent confirmations.
4. **Missing evidence is invisible.** When a tool fails, is not installed, or a media stream is absent, most pipelines silently continue.
5. **Integrity and audit are bolted on.** Hashes, timestamps and reviewer decisions are rarely part of the analysis output itself.

## What "good" needs to look like
- Exact evidence identity (cryptographic hash) established before anything else touches the file.
- Measurements that can be re-run and re-checked, each with limitations and benign alternatives.
- Competing hypotheses that include the boring explanation.
- Visible contradictions and gaps.
- A named human who reviews and signs off, and an audit trail that shows it.

## Quantified pain
The team did **not** collect our own time-loss or error-rate data, and we deliberately do not quote invented statistics. The problem is
framed from the published guidance we designed against: NIST SP 800-86 (digital-forensic practice: integrity checking with message
digests, documentation, process control), ISO/IEC 27037 (identification, collection, acquisition and preservation of digital
evidence), and, for India, the electronic-record provisions and section 63(4)(c) certificate schedule of the Bharatiya Sakshya
Adhiniyam, 2023 (source/device details and hash values). See `src/EMAFIG-COURT-READINESS.md`.

## Why now
Generative video and voice tools are cheap and widely available, so the volume of contestable media evidence is rising while
courtroom expectations for reproducibility and traceability are not relaxing. Workflow-level tooling (evidence preservation, audit,
review) is the gap that no single better classifier closes. LLM agents such as IBM Bob make the investigation workflow itself
operable in natural language, provided they are kept bounded and cannot invent facts.
