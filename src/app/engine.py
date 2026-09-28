
from __future__ import annotations
import asyncio, json, os, traceback
from pathlib import Path
from typing import Callable
from app.schemas import CaseState, AgentRun, Observation, Hypothesis
from app.store import CaseStore
from app.utils import utcnow, new_id, media_type, environment_identity, sha256_file, sha512_file
from app.agents import intake, metadata, visual, temporal, compression, audio, av_sync, provenance
from app.bob import BobClient

class InvestigationEngine:
    def __init__(self, store: CaseStore):
        self.store=store
        self.bob=BobClient()

    def _agent(self, case, agent_id, version):
        case.agent_runs[agent_id]=AgentRun(agent_id=agent_id,version=version,status="queued")

    async def create_case(self, src: Path, description: str|None=None, case_id: str|None=None) -> CaseState:
        case_id=case_id or f"CASE-{utcnow().replace('-','').replace(':','').replace('.','')[:15]}-{new_id('X').split('-')[-1]}"
        case_dir=self.store.case_dir(case_id)
        art=intake.ingest(src,case_dir,case_id)
        now=utcnow()
        state=CaseState(case_id=case_id,evidence_id=new_id("EVD"),filename=src.name,
                        media_type=art["type"],status="running",stage="examiners",
                        created_utc=now,updated_utc=now,source_description=description,
                        original=art)
        for aid,ver in [
            ("metadata-analysis","2.0.0"),("compression-analysis","2.0.0"),
            ("visual-forensics","2.0.0"),("audio-forensics","2.1.0"),
            ("temporal-analysis","2.0.0"),("av-sync-analysis","2.0.0"),
            ("c2pa-provenance","2.0.0")
        ]: self._agent(state,aid,ver)
        self.store.save(state)
        self.store.ledger(case_id).append("CASE_CREATED",case_id,{"original":art,"environment":environment_identity()})
        await self._run_examiner_stage(state)
        return state

    async def _one(self,state,aid,fn):
        ar=state.agent_runs[aid]; ar.status="running"; ar.started_utc=utcnow(); start=asyncio.get_running_loop().time()
        self.store.save(state)
        try:
            obs,arts,warns=await asyncio.to_thread(fn)
            ar.status="completed_with_warnings" if warns else "completed"
            ar.warnings.extend(warns)
            for o in obs:
                state.observations.append(o); ar.observation_ids.append(o.observation_id)
            for a in arts:
                ar.artifact_ids.append(a.get("sha256","")[:16])
            self.store.ledger(state.case_id).append("AGENT_COMPLETED",state.case_id,
                {"agent":aid,"status":ar.status,"observations":len(obs),"artifacts":len(arts),"warnings":warns})
        except Exception as e:
            ar.status="failed"; ar.error=repr(e); state.errors.append(f"{aid}: {e}")
            self.store.ledger(state.case_id).append("AGENT_FAILED",state.case_id,{"agent":aid,"error":repr(e)})
        ar.ended_utc=utcnow(); ar.duration_ms=int((asyncio.get_running_loop().time()-start)*1000)
        state.updated_utc=utcnow(); self.store.save(state)

    async def _run_examiner_stage(self,state):
        case_dir=self.store.case_dir(state.case_id); out=case_dir/"artifacts"; work=case_dir/"working"
        media=Path(state.original.path); mt=state.media_type
        tasks=[
            self._one(state,"metadata-analysis",lambda: metadata.run(media,out,state.evidence_id)),
            self._one(state,"compression-analysis",lambda: compression.run(media,out,state.evidence_id,mt)),
            self._one(state,"visual-forensics",lambda: visual.run(media,out,state.evidence_id,mt)),
            self._one(state,"audio-forensics",lambda: audio.run(media,out,state.evidence_id,Path(os.getenv("AASIST_MODEL","models/audio/aasist.onnx")))),
            self._one(state,"temporal-analysis",lambda: temporal.run(media,out,state.evidence_id)) if mt=="video" else self._mark_na(state,"temporal-analysis","not_applicable"),
            self._one(state,"av-sync-analysis",lambda: av_sync.run(media,out,state.evidence_id,mt)) if mt=="video" else self._mark_na(state,"av-sync-analysis","not_applicable"),
            self._one(state,"c2pa-provenance",lambda: provenance.run(media,out,state.evidence_id)),
        ]
        await asyncio.gather(*tasks)
        state.stage="reasoning"; state.status="running"; state.updated_utc=utcnow(); self.store.save(state)
        await self._run_reasoning(state)

    async def _mark_na(self,state,aid,status):
        ar=state.agent_runs[aid]; ar.status=status; ar.started_utc=ar.ended_utc=utcnow()
        self.store.ledger(state.case_id).append("AGENT_NOT_APPLICABLE",state.case_id,{"agent":aid})

    async def _run_reasoning(self,state):
        packet={
            "case_id":state.case_id,"evidence_id":state.evidence_id,
            "original_hash":state.original.sha256,
            "media_type":state.media_type,
            "observations":[o.model_dump() for o in state.observations],
            "agent_status":{k:v.status for k,v in state.agent_runs.items()}
        }
        modes=["hypothesis-assessor","skeptic","adversarial","legal-proposer"]
        results={}
        for mode in modes:
            results[mode]=await asyncio.to_thread(self.bob.ask,mode,packet)
        state.bob=results
        hs=results.get("hypothesis-assessor",{}).get("response",results.get("hypothesis-assessor",{}).get("fallback",{})).get("hypotheses",[])
        if not hs: hs=self.bob._mock("hypothesis-assessor",packet)["hypotheses"]
        state.hypotheses=[Hypothesis(id=h["id"],label=h["label"],description=h["description"]) for h in hs]
        self._map_hypotheses(state)
        self._contradictions(state)
        self._missing(state)
        state.stage="report"; state.status="awaiting_review"; state.updated_utc=utcnow(); self.store.save(state)
        self.store.ledger(state.case_id).append("REASONING_COMPLETED",state.case_id,{"hypotheses":[h.model_dump() for h in state.hypotheses]})

    def _map_hypotheses(self,state):
        for o in state.observations:
            # Deterministic coarse mapping; Bob's narrative remains separate.
            if o.supports:
                for h in state.hypotheses:
                    if h.id in o.supports: h.support_observation_ids.append(o.observation_id)
            for h in state.hypotheses:
                if h.id in o.contradicts: h.contradiction_observation_ids.append(o.observation_id)
        # Every observation not explicitly mapped is retained as uninformative.
        for h in state.hypotheses:
            used=set(h.support_observation_ids+h.contradiction_observation_ids)
            h.uninformative_observation_ids=[o.observation_id for o in state.observations if o.observation_id not in used]

    def _contradictions(self,state):
        state.contradictions=[]
        for h in state.hypotheses:
            if h.support_observation_ids and h.contradiction_observation_ids:
                state.contradictions.append({
                    "hypothesis_id":h.id,"support":h.support_observation_ids,
                    "contradiction":h.contradiction_observation_ids,
                    "status":"unresolved"
                })

    def _missing(self,state):
        gaps=[]
        for aid,ar in state.agent_runs.items():
            if ar.status in {"failed","not_applicable"}:
                gaps.append({"item":aid,"status":ar.status,"impact":"Corresponding evidence channel is unavailable."})
            elif ar.status=="completed_with_warnings":
                gaps.append({"item":aid,"status":"warnings","impact":ar.warnings})
        if not state.original.sha256: gaps.append({"item":"original_hash","status":"missing","impact":"Integrity baseline unavailable."})
        state.missing_evidence=gaps

    def review(self,state,observation_id,status,reviewer,reason):
        for o in state.observations:
            if o.observation_id==observation_id:
                o.review_status=status
                self.store.ledger(state.case_id).append("HUMAN_REVIEW",state.case_id,{"observation_id":observation_id,"status":status,"reviewer":reviewer,"reason":reason})
                state.updated_utc=utcnow(); self.store.save(state); return state
        raise KeyError(observation_id)

    def generate_report(self,state,signoff:dict|None=None):
        report_dir=self.store.case_dir(state.case_id)/"reports"
        report_dir.mkdir(exist_ok=True)
        packet={
            "schema_version":"EMAFIG-EVIDENCE-1.0","generated_utc":utcnow(),
            "case":state.model_dump(),
            "traceability":{
                "original_sha256":state.original.sha256,"original_sha512":state.original.sha512,
                "ledger":self.store.ledger(state.case_id).verify()
            },
            "limitations":[
                "Automated screening is not a binary truth detector.",
                "Model scores are not probabilities unless a validated operating point and population are supplied.",
                "C2PA absence is a provenance gap, not proof of manipulation.",
                "Legal mapping is advisory and requires qualified human review."
            ]
        }
        raw=report_dir/"forensic_package.json"; raw.write_text(json.dumps(packet,indent=2,default=str),encoding="utf-8")
        # Judge-friendly Markdown.
        md=self._markdown(packet)
        mdp=report_dir/"forensic_report.md"; mdp.write_text(md,encoding="utf-8")
        state.reports={"json":str(raw),"markdown":str(mdp)}
        state.human_review["signoff"]=signoff
        state.status="complete" if signoff else "awaiting_signoff"
        state.updated_utc=utcnow(); self.store.save(state)
        self.store.ledger(state.case_id).append("REPORT_GENERATED",state.case_id,{"json":str(raw),"markdown":str(mdp)})
        if signoff:
            self.store.ledger(state.case_id).append("CASE_SIGNED_OFF",state.case_id,signoff)
        return state

    def _markdown(self,p):
        c=p["case"]; obs=c["observations"]; hs=c["hypotheses"]
        lines=[f"# EMAFIG Forensic Investigation — {c['case_id']}","",
               "## Executive status",
               f"- Media: `{c['filename']}` ({c['media_type']})",
               f"- SHA-256: `{c['original']['sha256']}`",
               f"- SHA-512: `{c['original']['sha512']}`",
               f"- Automated status: `{c['status']}`","",
               "## Agent coverage",""]
        for k,v in c["agent_runs"].items():
            lines.append(f"- **{k}** — {v['status']} — {len(v['observation_ids'])} observations")
        lines += ["","## Observations",""]
        for o in obs:
            lines += [f"### {o['observation_id']} — {o['type']}",
                      o["statement"],
                      f"- Measurement: `{json.dumps(o['measurement'],ensure_ascii=False)}`",
                      f"- Alternatives: {', '.join(o['alternative_explanations']) or 'none recorded'}",
                      f"- Calibrated: `{o['calibrated']}`",""]
        lines += ["## Competing hypotheses",""]
        for h in hs:
            lines += [f"### {h['id']} — {h['label']}",h["description"],
                      f"- Supporting observations: {', '.join(h['support_observation_ids']) or 'none'}",
                      f"- Contradicting observations: {', '.join(h['contradiction_observation_ids']) or 'none'}",""]
        lines += ["## Contradictions",""]
        lines += [f"- `{json.dumps(x)}`" for x in c["contradictions"]] or ["- None recorded."]
        lines += ["","## Evidence gaps",""]
        lines += [f"- **{x['item']}** — {x['status']}: {x['impact']}" for x in c["missing_evidence"]] or ["- No pipeline gaps recorded."]
        lines += ["","## Legal / evidence packaging",
                   "Legal references are candidates only and require human legal review.",
                   "The evidence package preserves hashes, tool/agent status, observations and audit-chain state.",
                   "","## Limitations"]+["- "+x for x in p["limitations"]]
        return "\n".join(lines)
