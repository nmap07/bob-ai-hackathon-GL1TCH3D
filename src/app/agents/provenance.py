"""
app/agents/provenance.py
C2PA / Content Credentials examiner.

Order of preference: c2pa-python (in requirements) -> c2patool CLI -> byte-marker
screen. Absence of a manifest is recorded as a provenance gap, never as
evidence of manipulation (plan principle 11).
"""
from __future__ import annotations
import json
from pathlib import Path
from app.schemas import Observation
from app.utils import new_id, sha256_file, run_cmd
from app.forensics.tooling import resolve_executable

AGENT_ID="c2pa-provenance"; VERSION="3.0.0"

# IPTC digital source types that declare generative / algorithmic media.
AI_SOURCE_TYPES=("trainedalgorithmicmedia","compositewithtrainedalgorithmicmedia","algorithmicmedia",
                 "compositesynthetic")
_MARKERS=(b"c2pa",b"contentcredentials",b"jumb")

def _save(data, out: Path, prefix: str) -> dict:
    raw=out/f"{prefix}_{new_id('RAW')}.json"
    raw.write_text(data if isinstance(data,str) else json.dumps(data,indent=2,default=str),encoding="utf-8")
    return {"path":str(raw),"sha256":sha256_file(raw),"type":"json"}

def _summarise_manifest(store: dict) -> dict:
    text=json.dumps(store).lower()
    ai=[t for t in AI_SOURCE_TYPES if t in text]
    active=store.get("active_manifest")
    manifest=(store.get("manifests") or {}).get(active,{}) if active else {}
    return {"manifest_present":True,"active_manifest":active,
            "claim_generator":manifest.get("claim_generator") or (manifest.get("claim_generator_info") or [{}])[0].get("name"),
            "signature_issuer":(manifest.get("signature_info") or {}).get("issuer"),
            "validation_status":store.get("validation_status") or [],
            "validation_state":store.get("validation_state"),
            "ai_generated_assertion":bool(ai),"ai_source_types":ai}

def _marker_scan(media: Path, chunk=1<<20) -> bool:
    tail=b""
    with media.open("rb") as f:
        while b:=f.read(chunk):
            window=(tail+b).lower()
            if any(m in window for m in _MARKERS): return True
            tail=b[-32:]
    return False

def _obs(type_, statement, measurement, evidence_id, **kw):
    return Observation(observation_id=new_id("OBS"),agent_id=AGENT_ID,agent_version=VERSION,type=type_,
                       statement=statement,measurement=measurement,basis=[evidence_id],calibrated=False,**kw)

def run(media: Path, out: Path, evidence_id: str):
    obs=[]; arts=[]; warnings=[]
    lim=["Presence/absence of C2PA provenance is not a truth or deepfake verdict.",
         "Most viral and messaging-app media carries no C2PA manifest."]
    try:
        import c2pa
        try:
            reader=c2pa.Reader(str(media))
            store=json.loads(reader.json())
            try: store.setdefault("validation_state",reader.get_validation_state())
            except Exception: pass
            summary=_summarise_manifest(store)
            arts.append(_save(store,out,"c2pa_manifest"))
        except Exception as e:
            if "notfound" not in type(e).__name__.lower() and "no jumbf" not in str(e).lower():
                raise
            summary={"manifest_present":False,"verified":True,"reason":str(e)}
        summary["tool"]=f"c2pa-python (sdk {c2pa.sdk_version()})"
        if summary["manifest_present"]:
            invalid=[s for s in summary["validation_status"] if isinstance(s,dict) and "fail" in str(s.get("code","")).lower()] \
                    or str(summary.get("validation_state","")).lower()=="invalid"
            summary["validation_failed"]=bool(invalid)
            stmt=(f"C2PA manifest found (generator: {summary.get('claim_generator') or 'unknown'}); "
                  f"validation {'FAILED' if invalid else 'passed'}"
                  f"{'; declares AI/algorithmic source' if summary['ai_generated_assertion'] else ''}.")
        else:
            stmt="No C2PA manifest found (c2pa-python)."
        obs.append(_obs("provenance.c2pa",stmt,summary,evidence_id,limitations=lim,
                        alternative_explanations=["manifest stripped by platform","capture device without C2PA support"]))
        return obs,arts,warnings
    except ImportError:
        warnings.append("c2pa-python not installed; trying c2patool.")
    except Exception as e:
        warnings.append(f"c2pa-python failed: {e!r}; trying c2patool.")

    tool=resolve_executable("c2patool")
    if tool["available"]:
        rc,stdout,stderr=run_cmd([tool["path"],str(media)],timeout=60)
        arts.append(_save(stdout or stderr,out,"c2pa"))
        present=rc==0 and stdout.strip().startswith("{")
        summary={"manifest_present":present,"tool":f"c2patool {tool['version']}","exit_code":rc}
        if present:
            try: summary.update(_summarise_manifest(json.loads(stdout)))
            except json.JSONDecodeError: pass
        obs.append(_obs("provenance.c2pa",f"c2patool returned exit code {rc}; manifest {'present' if present else 'not found'}.",
                        summary,evidence_id,limitations=lim))
        return obs,arts,warnings

    marker=_marker_scan(media)
    obs.append(_obs("provenance.c2pa_marker_screen",
        ("C2PA-related byte markers were detected." if marker else "No C2PA-related byte markers were detected."),
        {"marker_detected":marker,"verified":False},evidence_id,
        alternative_explanations=["unsupported embedding","stripped metadata"],
        limitations=lim+["Marker screen is not C2PA verification. Install c2pa-python for manifest validation."]))
    warnings.append("No C2PA validator available; provenance was not cryptographically verified.")
    return obs,arts,warnings
