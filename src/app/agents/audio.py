
from __future__ import annotations
from pathlib import Path
from app.schemas import Observation, AgentRun
from app.utils import utcnow, new_id, sha256_file, sha512_file, run_cmd, tool_version

import json, math, shutil, wave
import numpy as np

AGENT_ID="audio-forensics"; VERSION="2.1.0"

def _extract(media: Path, work: Path):
    wav=work/f"audio_{new_id('DER')}.wav"
    if media.suffix.lower() in {".wav",".flac",".mp3",".m4a",".aac",".ogg",".opus"}:
        if media.suffix.lower()==".wav":
            return media
    if not shutil.which("ffmpeg"): return None
    rc,_,err=run_cmd(["ffmpeg","-y","-i",str(media),"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(wav)],timeout=180)
    return wav if rc==0 and wav.exists() else None

def _aasist(wav: Path, model_path: Path):
    try:
        import onnxruntime as ort
    except Exception as e:
        return {"status":"not_available","reason":f"onnxruntime not installed: {e}"}
    try:
        import soundfile as sf
        y,sr=sf.read(str(wav),dtype="float32")
        if y.ndim>1: y=y.mean(axis=1)
        if sr!=16000: return {"status":"failed","reason":f"expected 16000 Hz, got {sr}"}
        target=64600
        if len(y)<target: y=np.pad(y,(0,target-len(y)))
        else: y=y[:target]
        sess=ort.InferenceSession(str(model_path),providers=["CPUExecutionProvider"])
        inp=sess.get_inputs()[0]
        arr=y.astype("float32")[None,:]
        outputs=sess.run(None,{inp.name:arr})
        vals=np.asarray(outputs[0]).reshape(-1).tolist()
        return {"status":"completed","input_name":inp.name,"output":vals,
                "output_names":[x.name for x in sess.get_outputs()],
                "note":"AASIST raw score/logit is preserved. No unvalidated fake/real threshold is applied."}
    except Exception as e:
        return {"status":"failed","reason":repr(e)}

def run(media: Path, out: Path, evidence_id: str, model_path: Path):
    obs=[]; arts=[]; warnings=[]
    wav=_extract(media,out)
    if not wav:
        return obs,arts,["No decodable audio stream or ffmpeg unavailable."]
    try:
        import librosa
        y,sr=librosa.load(str(wav),sr=16000,mono=True)
        if len(y)==0: return obs,arts,["Audio stream is empty."]
        rms=librosa.feature.rms(y=y)[0]; centroid=librosa.feature.spectral_centroid(y=y,sr=sr)[0]
        spec=np.abs(librosa.stft(y)); flux=np.sqrt(np.sum(np.diff(spec,axis=1)**2,axis=0))
        flux_mean=float(np.mean(flux)); flux_std=float(np.std(flux))
        spikes=np.where(flux>flux_mean+3*flux_std)[0].tolist()
        result={"duration_s":len(y)/sr,"sample_rate":sr,"rms_mean":float(np.mean(rms)),
                "rms_std":float(np.std(rms)),"spectral_centroid_mean":float(np.mean(centroid)),
                "spectral_flux_spikes":len(spikes),"spike_indices":spikes[:100]}
        raw=out/f"audio_forensics_{new_id('RAW')}.json"; raw.write_text(json.dumps(result,indent=2),encoding="utf-8")
        arts.append({"path":str(raw),"sha256":sha256_file(raw),"type":"json"})
        obs.append(Observation(
            observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,
            type="audio.spectral_profile",statement=f"Audio decoded at {sr} Hz; {len(spikes)} spectral-flux spikes exceeded the 3-sigma screening threshold.",
            measurement=result,basis=[evidence_id],calibrated=False,
            supports=["H2","H3","H5"] if spikes else [],
            alternative_explanations=["speech consonants","background events","editing boundaries","codec behavior"],
            limitations=["Spectral discontinuity is not specific to synthetic speech."]
        ))
    except Exception as e:
        warnings.append(f"librosa analysis failed: {e}")
    if model_path.exists():
        model_result=_aasist(wav,model_path)
        raw=out/f"aasist_{new_id('RAW')}.json"; raw.write_text(json.dumps(model_result,indent=2),encoding="utf-8")
        arts.append({"path":str(raw),"sha256":sha256_file(raw),"type":"json"})
        if model_result.get("status")=="completed":
            obs.append(Observation(
                observation_id=new_id("OBS"),agent_id="audio-deepfake-aasist",agent_version="AASIST-ONNX",
                type="audio.deepfake_model_signal",
                statement="AASIST produced a raw anti-spoofing model score; higher values are associated with bona-fide speech in the referenced model implementation.",
                measurement={"raw_output":model_result.get("output"),"model":"AASIST","sample_rate":16000},
                basis=[evidence_id],calibrated=False,
                alternative_explanations=["domain shift","codec/channel mismatch","unseen synthesis methods","non-speech audio"],
                limitations=["Do not convert the raw score to a legal or forensic probability without a validated operating point on the relevant population."]
            ))
        else:
            warnings.append(model_result.get("reason","AASIST failed"))
    else:
        warnings.append("AASIST model not installed. Place aasist.onnx under models/audio or set AASIST_MODEL.")
    return obs,arts,warnings
