
from __future__ import annotations
import json, os, urllib.request
from typing import Any

class BobClient:
    """
    Boundary for IBM Bob reasoning.

    Modes:
      mock: deterministic offline fallback for judging/demo.
      http: POSTs a JSON request to BOB_BASE_URL using BOB_API_KEY.
            The exact gateway contract is intentionally configurable because
            the Bob endpoint/model contract is supplied by the hackathon account.
    """
    def __init__(self):
        self.mode=os.getenv("BOB_MODE","mock").lower()
        self.url=os.getenv("BOB_BASE_URL","").rstrip("/")
        self.key=os.getenv("BOB_API_KEY","")
        self.model=os.getenv("BOB_MODEL","")
        self.calls=0

    def ask(self, mode: str, payload: dict[str,Any]) -> dict:
        self.calls += 1
        if self.mode=="http" and self.url:
            body={"model":self.model,"mode":mode,"input":payload}
            req=urllib.request.Request(self.url, data=json.dumps(body).encode(),
                headers={"Content-Type":"application/json",**({"Authorization":f"Bearer {self.key}"} if self.key else {})},
                method="POST")
            try:
                with urllib.request.urlopen(req,timeout=120) as r:
                    return {"status":"ok","provider":"bob","mode":mode,"response":json.loads(r.read().decode())}
            except Exception as e:
                return {"status":"fallback","provider":"bob-http","mode":mode,"error":repr(e),
                        "fallback":self._mock(mode,payload)}
        return {"status":"ok","provider":"mock-bob","mode":mode,"response":self._mock(mode,payload)}

    def _mock(self,mode,p):
        obs=p.get("observations",[])
        if mode=="hypothesis-assessor":
            hs=[
                {"id":"H1","label":"Authentic recording","description":"The submitted media is consistent with an authentic capture, subject to gaps and limitations."},
                {"id":"H2","label":"Manipulated face/content","description":"Some media content was altered after capture or generated synthetically."},
                {"id":"H3","label":"Fully synthetic/generated media","description":"The media was generated or substantially synthesized rather than captured as presented."},
                {"id":"H4","label":"Authentic media with benign post-processing","description":"Observed anomalies are explained by legitimate editing, resizing, transcoding or platform processing."},
                {"id":"H5","label":"Manipulated content subsequently re-encoded","description":"Manipulation may have been followed by ordinary transcoding or redistribution processing."},
            ]
            return {"hypotheses":hs,"reasoning_note":"Candidate hypotheses only; evidence must be assessed by the investigator."}
        if mode=="skeptic":
            return {"challenges":[
                {"observation_id":o.get("observation_id"),"challenge":"Check whether the observation has a benign technical explanation before treating it as manipulation evidence."}
                for o in obs
            ]}
        if mode=="adversarial":
            return {"tests":[
                "Re-check suspicious intervals on the original-resolution file.",
                "Compare against an independently sourced copy if available.",
                "Repeat analysis after documenting codec/transcoding conditions.",
                "Do not count multiple detectors using the same frames as independent corroboration."
            ]}
        if mode=="legal-proposer":
            return {"status":"review_required","candidates":[],"note":"Legal provisions must come from the versioned approved ruleset; Bob must not invent section numbers."}
        if mode=="brief":
            return {"brief":"The investigation compiled metadata, visual, audio, temporal, synchronization, compression and provenance observations. Findings remain subject to human forensic review and source-chain limitations."}
        return {"summary":"Reasoning completed from structured observations."}
