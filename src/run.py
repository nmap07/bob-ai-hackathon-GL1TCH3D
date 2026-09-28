import argparse, asyncio, json
from pathlib import Path
from app.store import CaseStore
from app.engine import InvestigationEngine

def main():
    ap=argparse.ArgumentParser(description="EMAFIG forensic investigation runner")
    ap.add_argument("evidence")
    ap.add_argument("--description",default="")
    ap.add_argument("--case-id",default=None,dest="case_id")
    ap.add_argument("--officer",default=None,help="officer name recorded in custody and ledger")
    ap.add_argument("--how-received",default=None,dest="how_received")
    ap.add_argument("--report",action="store_true",help="also write the draft report package")
    args=ap.parse_args()
    root=Path(__file__).resolve().parent
    engine=InvestigationEngine(CaseStore(root/"cases"))
    c=asyncio.run(engine.create_case(Path(args.evidence),args.description,args.case_id,
                                     {"officer_name":args.officer,"how_received":args.how_received}))
    if args.report:
        c=engine.generate_report(c.case_id)
    print(json.dumps({"case_id":c.case_id,"status":c.status,"sha256":c.original.sha256,
                      "risk_index":c.risk.get("risk_score"),"band":c.risk.get("band"),
                      "triage":{k:c.triage.get(k) for k in ("likelihood_band","probability_manipulated","probability_label","provider")},
                      "agents":{k:v.status for k,v in c.agent_runs.items()},"reports":c.reports},indent=2))
    print("Sign-off requires human review in the UI (two different people). Triage numbers are not evidence.")

if __name__=="__main__": main()
