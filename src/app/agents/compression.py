
from __future__ import annotations
from pathlib import Path
from app.schemas import Observation, AgentRun
from app.utils import utcnow, new_id, sha256_file, sha512_file, run_cmd, tool_version

import cv2, json, numpy as np

AGENT_ID="compression-analysis"; VERSION="2.0.0"

def run(media: Path, out: Path, evidence_id: str, media_type: str):
    obs=[]; arts=[]; warnings=[]
    if media_type=="video":
        cap=cv2.VideoCapture(str(media)); frames=[]
        for i in range(8):
            ok,frame=cap.read()
            if not ok: break
            frames.append(frame)
        cap.release()
    elif media_type=="image":
        img=cv2.imread(str(media)); frames=[img] if img is not None else []
    else: frames=[]
    if not frames:
        return obs,arts,["No frames available for compression screening."]
    scores=[]
    for f in frames:
        gray=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
        lap=float(np.var(cv2.Laplacian(gray,cv2.CV_64F)))
        scores.append(lap)
    raw=out/f"compression_{new_id('RAW')}.json"
    raw.write_text(json.dumps({"laplacian_variance":scores},indent=2),encoding="utf-8")
    arts.append({"path":str(raw),"sha256":sha256_file(raw),"type":"json"})
    obs.append(Observation(
        observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,
        type="compression.sharpness_screen",statement=f"Sampled frame sharpness using Laplacian variance; mean {float(np.mean(scores)):.2f}.",
        measurement={"mean_laplacian_variance":float(np.mean(scores)),"std":float(np.std(scores))},
        basis=[evidence_id],calibrated=False,
        alternative_explanations=["focus","resize","denoising","codec quantization","source-camera processing"],
        limitations=["This is a screening metric, not a compression/deepfake classifier."]
    ))
    return obs,arts,warnings
