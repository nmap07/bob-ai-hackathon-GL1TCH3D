
from __future__ import annotations
from pathlib import Path
from app.schemas import Observation, AgentRun
from app.utils import utcnow, new_id, sha256_file, sha512_file, run_cmd, tool_version

import json, shutil

AGENT_ID="c2pa-provenance"; VERSION="2.0.0"

def run(media: Path, out: Path, evidence_id: str):
    obs=[]; arts=[]; warnings=[]
    if shutil.which("c2patool"):
        rc,stdout,stderr=run_cmd(["c2patool",str(media)],timeout=60)
        raw=out/f"c2pa_{new_id('RAW')}.json"; raw.write_text(stdout or stderr,encoding="utf-8")
        arts.append({"path":str(raw),"sha256":sha256_file(raw),"type":"json"})
        obs.append(Observation(
            observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,
            type="provenance.c2pa",statement=f"c2patool returned exit code {rc}.",
            measurement={"exit_code":rc,"tool":"c2patool","raw_output_path":str(raw)},
            basis=[evidence_id],calibrated=True,
            limitations=["Presence/absence of C2PA provenance is not a truth or deepfake verdict."]
        ))
    else:
        # Conservative marker-only fallback; explicitly not a verification.
        data=media.read_bytes()
        marker=(b"c2pa" in data.lower() or b"contentcredentials" in data.lower())
        obs.append(Observation(
            observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,
            type="provenance.c2pa_marker_screen",
            statement=("C2PA-related byte markers were detected." if marker else "No C2PA-related byte markers were detected."),
            measurement={"marker_detected":marker,"verified":False},basis=[evidence_id],
            calibrated=False,alternative_explanations=["unsupported embedding","stripped metadata"],
            limitations=["Marker screen is not C2PA verification. Install c2patool or c2pa-python for actual manifest validation."]
        ))
        warnings.append("c2patool unavailable; provenance was not cryptographically verified.")
    return obs,arts,warnings
