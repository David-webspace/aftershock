"""回信解析實測：用目前設定的模型跑完整個詢問流程，與模擬的實際狀況逐筆比對。

python -m app.evals.replies hualien-2024 tohoku-2011     （會呼叫模型；本機 Ollama 不花錢，雲端模型會產生費用）

每個供應商廠區落在三種結果之一：
- 自動採用且正確：狀態一致；停工或部分運作時恢復日相差 2 天內
- 自動採用但錯誤：最危險，錯的數字會直接進曝險計算
- 交人確認：驗證沒過（含糊、缺日期、依據不在原文），不會自動採用
"""

import json
import sys
import time
from collections import Counter

from sqlalchemy import select

from app.auth import load_principal
from app.db import SessionLocal
from app.llm import get_llm
from app.models import Incident, Message, SiteStatus, Supplier, Truth
from app.sim import supplier as sim
from app.workflow import incident as wf


def run(key: str) -> dict:
    llm = get_llm()
    started = time.monotonic()
    with SessionLocal() as db:
        boss = load_principal(db, "scm.manager")
        inc = wf.open_incident(db, key, boss)
        for _ in range(6):
            for m in db.scalars(select(Message).where(Message.incident_id == inc.id, Message.status == "draft")).all():
                wf.approve(db, m.id, boss)
            wf.advance(db, inc, 24, llm, boss)
        rows, outcome = [], Counter()
        for st in db.scalars(select(SiteStatus).where(SiteStatus.incident_id == inc.id)).all():
            t = db.get(Truth, (inc.id, st.supplier_id, st.site_key))
            if st.state == "replied":
                ok = st.operating == t.operating and (t.operating == "normal" or abs((st.resume_day or -99) - t.resume_day) <= 2)
                result = "auto_correct" if ok else "auto_wrong"
            else:
                result = "review" if st.state == "needs_review" else st.state
            outcome[result] += 1
            rows.append({"supplier": st.supplier_id, "site": st.site_key, "style": sim.style(key, st.supplier_id),
                         "language": db.get(Supplier, st.supplier_id).language, "truth": [t.operating, t.resume_day],
                         "got": [st.operating, st.resume_day], "result": result})
        calls = db.scalars(select(Message).where(Message.incident_id == inc.id, Message.direction == "in")).all()
        db.delete(db.get(Incident, inc.id))
        db.commit()
    return {"scenario": key, "sites": len(rows), "outcome": dict(outcome), "replies_parsed": len(calls),
            "seconds": round(time.monotonic() - started), "rows": rows}


if __name__ == "__main__":
    for k in sys.argv[1:]:
        r = run(k)
        print(json.dumps({x: r[x] for x in ("scenario", "sites", "outcome", "replies_parsed", "seconds")}, ensure_ascii=False))
        for row in r["rows"]:
            if row["result"] != "auto_correct":
                print("  ", json.dumps(row, ensure_ascii=False))
