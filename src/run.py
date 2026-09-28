
import argparse, asyncio
from pathlib import Path
from app.store import CaseStore
from app.engine import InvestigationEngine

def main():
    ap=argparse.ArgumentParser(description="EMAFIG forensic investigation runner")
    ap.add_argument("evidence")
    ap.add_argument("--description",default="")
    ap.add_argument("--case-id",default=None,dest="case_id")
    ap.add_argument("--signoff",action="store_true")
    args=ap.parse_args()
    root=Path(__file__).resolve().parent
    engine=InvestigationEngine(CaseStore(root/"cases"))
    c=asyncio.run(engine.create_case(Path(args.evidence),args.description,args.case_id))
    if args.signoff:
        c=engine.generate_report(c,{"reviewer":"cli","statement":"Demo sign-off; replace with actual investigator review."})
    print(c.model_dump_json(indent=2))
if __name__=="__main__": main()
