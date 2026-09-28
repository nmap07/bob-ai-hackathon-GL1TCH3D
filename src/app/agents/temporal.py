
from __future__ import annotations
from pathlib import Path
from app.schemas import Observation, AgentRun
from app.utils import utcnow, new_id, sha256_file, sha512_file, run_cmd, tool_version

import json, cv2, numpy as np, math

AGENT_ID="temporal-analysis"; VERSION="2.1.0"

def _ffprobe():
    from app.forensics.tooling import resolve_executable
    return resolve_executable("ffprobe")["path"] or "ffprobe"

def run(media: Path, out: Path, evidence_id: str):
    obs=[]; arts=[]; warnings=[]
    rc,stdout,stderr=run_cmd([_ffprobe(),"-v","quiet","-print_format","json","-show_packets","-show_streams",str(media)],timeout=120)
    if rc!=0:
        return obs,arts,[f"ffprobe packet analysis failed: {stderr[-1000:]}"]
    raw=out/f"temporal_packets_{new_id('RAW')}.json"; raw.write_text(stdout,encoding="utf-8")
    arts.append({"path":str(raw),"sha256":sha256_file(raw),"type":"json"})
    try:
        data=json.loads(stdout); packets=[p for p in data.get("packets",[]) if p.get("codec_type")=="video"]
        pts=[]
        for p in packets:
            try: pts.append(float(p.get("pts_time")))
            except: pass
        # Packets arrive in decode order; with B-frames PTS is not monotonic, so
        # cadence must be measured in presentation order.
        pts.sort()
        diffs=np.diff(pts) if len(pts)>2 else np.array([])
        if len(diffs):
            med=float(np.median(diffs)); anomalies=[i for i,d in enumerate(diffs) if d<=0 or d>med*2.5]
            obs.append(Observation(
                observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,
                type="temporal.cadence",statement=f"Measured {len(pts)} video packet timestamps; median PTS interval {med:.6f}s.",
                measurement={"packet_count":len(pts),"median_interval_s":med,"anomaly_count":len(anomalies),
                             "anomaly_indices":anomalies[:50]},basis=[evidence_id],calibrated=False,
                supports=["H2","H5"] if anomalies else [],
                alternative_explanations=["variable frame rate","container timestamp behavior","transcoding"],
                limitations=["Packet timing anomalies are not proof of editing or synthesis."]
            ))
    except Exception as e: warnings.append(str(e))
    return obs,arts,warnings
