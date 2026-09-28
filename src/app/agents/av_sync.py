
from __future__ import annotations
from pathlib import Path
from app.schemas import Observation, AgentRun
from app.utils import utcnow, new_id, sha256_file, sha512_file, run_cmd, tool_version

import json, cv2, numpy as np

AGENT_ID="av-sync-analysis"; VERSION="2.0.0"

def _ffprobe():
    from app.forensics.tooling import resolve_executable
    return resolve_executable("ffprobe")["path"] or "ffprobe"

def run(media: Path, out: Path, evidence_id: str, media_type: str):
    obs=[]; arts=[]; warnings=[]
    if media_type!="video": return obs,arts,["AV synchronization is not applicable."]
    rc,stdout,stderr=run_cmd([_ffprobe(),"-v","quiet","-print_format","json","-show_streams",str(media)])
    if rc!=0: return obs,arts,[stderr[-1000:]]
    data=json.loads(stdout); vs=next((x for x in data.get("streams",[]) if x.get("codec_type")=="video"),{})
    au=next((x for x in data.get("streams",[]) if x.get("codec_type")=="audio"),{})
    if not vs or not au: return obs,arts,["Both video and audio streams are required."]
    vo=float(vs.get("start_time") or 0); ao=float(au.get("start_time") or 0); off=(vo-ao)*1000
    obs.append(Observation(
        observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,
        type="av_sync.stream_start_offset",statement=f"Container-reported video/audio start-time difference is {off:.2f} ms.",
        measurement={"offset_ms":off,"video_start_s":vo,"audio_start_s":ao},basis=[evidence_id],
        calibrated=False,supports=["H2","H5"] if abs(off)>50 else [],
        alternative_explanations=["container timestamps","muxing delay","VFR","decoder behavior"],
        limitations=["This is stream-level timing, not phoneme-to-mouth synchronization."]
    ))
    return obs,arts,warnings
