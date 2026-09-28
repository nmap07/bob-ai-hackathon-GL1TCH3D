
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any
from .schemas import CaseState, Observation, AgentRun
from .utils import utcnow, canonical, sha256_bytes

class HashChain:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _last(self):
        last = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip(): last = json.loads(line)
        return last

    def append(self, event: str, case_id: str, data: dict[str, Any]) -> dict:
        last = self._last()
        prev = last["hash"] if last else "0"*64
        entry = {"seq": (last["seq"]+1 if last else 1), "ts": utcnow(),
                 "event": event, "case_id": case_id, "data": data, "prev": prev}
        entry["hash"] = sha256_bytes((prev + canonical(entry)).encode())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical(entry)+"\n")
        return entry

    def verify(self) -> dict:
        prev = "0"*64; count = 0
        try:
            for line_no,line in enumerate(self.path.read_text(encoding="utf-8").splitlines(),1):
                if not line.strip(): continue
                e=json.loads(line); claimed=e.pop("hash"); count+=1
                if e.get("prev") != prev:
                    return {"valid":False,"entries":count,"error":f"prev mismatch at line {line_no}"}
                if sha256_bytes((prev+canonical(e)).encode()) != claimed:
                    return {"valid":False,"entries":count,"error":f"hash mismatch at line {line_no}"}
                prev=claimed
            return {"valid":True,"entries":count,"head":prev}
        except Exception as e:
            return {"valid":False,"entries":count,"error":str(e)}

class CaseStore:
    def __init__(self, root: str | Path = "cases"):
        self.root=Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.db=self.root/"cases.sqlite3"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS cases(
                case_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_utc TEXT NOT NULL)""")

    def case_dir(self, case_id): 
        p=self.root/case_id
        for d in ["original","working","artifacts","reports","audit","runs"]:
            (p/d).mkdir(parents=True,exist_ok=True)
        return p

    def save(self,state: CaseState):
        self.case_dir(state.case_id)
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT OR REPLACE INTO cases VALUES (?,?,?)",
                      (state.case_id,state.model_dump_json(),state.updated_utc))

    def load(self,case_id):
        with sqlite3.connect(self.db) as c:
            row=c.execute("SELECT state_json FROM cases WHERE case_id=?",(case_id,)).fetchone()
        return CaseState.model_validate_json(row[0]) if row else None

    def list_cases(self):
        with sqlite3.connect(self.db) as c:
            rows=c.execute("SELECT state_json FROM cases ORDER BY updated_utc DESC").fetchall()
        return [CaseState.model_validate_json(r[0]) for r in rows]

    def ledger(self,case_id): return HashChain(self.case_dir(case_id)/"audit"/"ledger.jsonl")
