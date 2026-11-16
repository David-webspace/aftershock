"""選定方案 → 產生信件：數量只能是方案中的數字、內部通知只有主管看得到、說明裡的數字必須出自方案。"""

import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main
from app.config import settings
from app.db import SessionLocal
from app.llm import Extraction
from app.models import Incident, Message
from app.plan.explain import explain, ungrounded


def login(c, user):
    c.cookies.clear()
    main.login_limit.hits.clear()
    assert c.post("/api/auth/login", json={"username": user, "password": os.environ["SEED_DEMO_PASSWORD"]}).status_code == 200


@pytest.fixture(scope="module")
def chosen():
    original = main.not_configured
    main.not_configured = lambda: "測試中不呼叫模型"
    httpx.delete(f"{settings.mailpit_api}/api/v1/messages")
    with TestClient(main.app) as c:
        login(c, "scm.manager")
        inc = c.post("/api/incidents", json={"scenario": "tohoku-2011"}).json()["id"]
        opts = c.get(f"/api/incidents/{inc}/options").json()
        login(c, "amy.chou")
        assert c.post(f"/api/incidents/{inc}/plan", json={"profile": "balanced"}).status_code == 403  # 只有主管能選方案
        login(c, "scm.manager")
        plan = c.post(f"/api/incidents/{inc}/plan", json={"profile": "balanced"}).json()
        yield c, inc, opts, plan
    main.not_configured = original
    with SessionLocal() as db:
        db.delete(db.get(Incident, inc))
        db.commit()


def test_drafts_follow_the_plan(chosen):
    c, inc, opts, plan = chosen
    with SessionLocal() as db:
        msgs = db.scalars(select(Message).where(Message.plan_id == plan["plan_id"])).all()
    balanced = next(o for o in opts["options"] if o["key"] == "balanced")
    n_suppliers = len({a["supplier_id"] for p in balanced["plans"] for a in p["actions"] if a["type"] == "extra_order"})
    n_transfers = sum(1 for p in balanced["plans"] for a in p["actions"] if a["type"] == "transfer")
    assert len([m for m in msgs if m.kind == "expedite"]) == n_suppliers
    assert len([m for m in msgs if m.kind == "transfer"]) == n_transfers
    assert all(m.status == "draft" and not m.guard_issues for m in msgs)


def test_internal_notice_is_manager_only_and_qty_is_locked(chosen):
    c, inc, _, plan = chosen
    with SessionLocal() as db:
        internal = db.scalars(select(Message).where(Message.plan_id == plan["plan_id"], Message.kind == "transfer")).first()
        ext = db.scalars(select(Message).where(Message.plan_id == plan["plan_id"], Message.kind == "expedite")).first()
    login(c, "cathy.wu")
    if internal:
        assert c.post(f"/api/messages/{internal.id}/approve").status_code == 404
    login(c, "scm.manager")
    r = c.patch(f"/api/messages/{ext.id}", json={"body": ext.body + "\n- 另外再加 99999 個"})
    assert any("核准方案以外的數量" in i for i in r.json()["guard_issues"])
    assert c.post(f"/api/messages/{ext.id}/approve").status_code == 422
    c.patch(f"/api/messages/{ext.id}", json={"body": ext.body})
    assert c.post(f"/api/messages/{ext.id}/approve").json()["status"] == "sent"
    found = httpx.get(f"{settings.mailpit_api}/api/v1/search", params={"query": f"subject:P{plan['plan_id']}"}).json()
    assert found["messages_count"] >= 1


def test_explanation_numbers_must_come_from_results(chosen):
    _, _, opts, _ = chosen

    class Says:
        def __init__(self, text):
            self.text = text

        def extract(self, *a, **k):
            return Extraction({"summary": self.text, "suggested": "balanced"}, "fake", 0, 0)

    good = explain(Says("三個方案的剩餘缺料相同：單一來源的電流感測器沒有可用手段，差別只在調撥量。"), opts)
    assert good["source"] == "fake" and good["suggested"] == "balanced"
    # 就算數字確實出現在結果裡，也可能被配錯方案（實測發生過），所以說明裡一律不准有數字
    o = next(x for x in opts["options"] if x["key"] == "balanced")
    bad = explain(Says(f"三個方案成本都是 {o['cost_usd']} 美元。"), opts)
    assert bad["source"] == "template" and "數字" in bad["note"]
    assert ungrounded("第 3 個方案比較省") == []
