"""應變流程端對端（真的寄到 Mailpit、真的從 Mailpit 收信；模型用假的，不花錢）。"""

import os
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main, scenarios
from app.config import settings
from app.db import SessionLocal
from app.llm import Extraction
from app.models import Incident, Message, SiteStatus, Supplier, Truth
from app.sim import supplier as sim
from app.workflow import incident as wf
from app.workflow import mail
from app.workflow.parse import parse

KEY = "hualien-2024"


class TruthLLM:
    """照實際狀況回答的假模型；evidence 取回信中提到該廠區的那一句。fabricate＝True 時故意給不在信裡的依據。"""

    def __init__(self, fabricate: bool = False):
        self.fabricate, self.calls = fabricate, 0
        self.incident_id = self.supplier_id = None

    def extract(self, system, user, tool_name, tool_description, schema):
        self.calls += 1
        keys = schema["properties"]["sites"]["items"]["properties"]["site_key"]["enum"]
        body = user.split("<信件>")[1].split("</信件>")[0]
        lines = [line for line in body.splitlines() if "：" in line or ":" in line] or body.splitlines()
        with SessionLocal() as db:
            t0 = scenarios.get(db.get(Incident, self.incident_id).scenario_key)["t0"].date()
            out = []
            for k in keys:
                t = db.get(Truth, (self.incident_id, self.supplier_id, k))
                out.append({"site_key": k, "operating": t.operating, "capacity_pct": t.capacity_pct,
                            "resume_date": (t0 + timedelta(days=t.resume_day)).isoformat() if t.operating != "normal" else None,
                            "damage": None, "evidence": "供應商說全部都沒問題" if self.fabricate else lines[0].strip()})
        return Extraction({"sites": out}, "fake", 0, 0)


@pytest.fixture(scope="module")
def client():
    httpx.delete(f"{settings.mailpit_api}/api/v1/messages")
    with TestClient(main.app) as c:
        yield c


def login(c, user):
    c.cookies.clear()
    main.login_limit.hits.clear()
    assert c.post("/api/auth/login", json={"username": user, "password": os.environ["SEED_DEMO_PASSWORD"]}).status_code == 200


@pytest.fixture(scope="module")
def incident(client):
    login(client, "scm.manager")
    incident_id = client.post("/api/incidents", json={"scenario": KEY}).json()["id"]
    yield incident_id
    with SessionLocal() as db:  # 測試開的應變案（連帶信件、狀態、模擬資料）不留在資料庫
        db.delete(db.get(Incident, incident_id))
        db.commit()


def draft_of(incident_id, style=None, commodity=None):
    with SessionLocal() as db:
        for m in db.scalars(select(Message).where(Message.incident_id == incident_id, Message.kind == "inquiry", Message.status == "draft")):
            sup = db.get(Supplier, m.supplier_id)
            if (style is None or sim.style(KEY, sup.id) == style) and (commodity is None or sup.commodity == commodity):
                return m.id, sup
    raise LookupError(style)


def buyer_for(commodity):
    return {"semiconductor": "amy.chou", "electromechanical": "amy.chou", "passive": "ben.lai", "magnetic": "ben.lai"}.get(commodity, "cathy.wu")


def test_drafts_are_clean_and_scoped(client, incident):
    login(client, "scm.manager")
    all_msgs = client.get(f"/api/incidents/{incident}/messages").json()
    assert all_msgs and all(m["status"] == "draft" and not m["guard_issues"] for m in all_msgs)
    assert all(m["to_addr"].endswith(".example") for m in all_msgs)
    login(client, "ben.lai")
    mine = client.get(f"/api/incidents/{incident}/messages").json()
    assert mine and {m["commodity"] for m in mine} <= {"passive", "magnetic"}
    other = next(m for m in all_msgs if m["commodity"] not in ("passive", "magnetic"))
    assert client.post(f"/api/messages/{other['id']}/approve").status_code == 404  # 別人負責的：當成不存在
    login(client, "sysadmin")
    assert client.get("/api/incidents").status_code == 403


def test_guard_blocks_other_supplier_and_prices(client, incident):
    msg_id, sup = draft_of(incident)
    login(client, buyer_for(sup.commodity))
    with SessionLocal() as db:
        other = db.scalars(select(Supplier.name).where(Supplier.id != sup.id)).first()
        body = db.get(Message, msg_id).body
    r = client.patch(f"/api/messages/{msg_id}", json={"body": body + f"\n\n參考：{other} 報價 USD 3.2"})
    assert len(r.json()["guard_issues"]) == 2
    assert client.post(f"/api/messages/{msg_id}/approve").status_code == 422
    assert client.patch(f"/api/messages/{msg_id}", json={"body": body}).json()["guard_issues"] == []


def test_reply_is_parsed_and_feeds_exposure(client, incident):
    msg_id, sup = draft_of(incident, style="complete")
    login(client, buyer_for(sup.commodity))
    assert client.post(f"/api/messages/{msg_id}/approve").json()["status"] == "sent"
    found = httpx.get(f"{settings.mailpit_api}/api/v1/search", params={"query": f"subject:AS-{incident}-{sup.id}"}).json()
    assert found["messages_count"] >= 1  # 真的寄到 Mailpit
    llm = TruthLLM()
    llm.incident_id, llm.supplier_id = incident, sup.id
    with SessionLocal() as db:
        inc = db.get(Incident, incident)
        out = wf.advance(db, inc, 40, llm, main.load_principal(db, "scm.manager"))
        assert out["received"] >= 1 and llm.calls >= 1
        sts = db.scalars(select(SiteStatus).where(SiteStatus.incident_id == incident, SiteStatus.supplier_id == sup.id)).all()
        for st in sts:
            t = db.get(Truth, (incident, sup.id, st.site_key))
            assert st.state == "replied" and st.operating == t.operating and st.resume_day == t.resume_day
        assert wf.overrides(db, inc)  # 回覆的狀況取代規劃假設，回饋到曝險計算


def test_silent_supplier_gets_follow_up(client, incident):
    msg_id, sup = draft_of(incident, style="silent")
    login(client, buyer_for(sup.commodity))
    client.post(f"/api/messages/{msg_id}/approve")
    llm = TruthLLM()
    llm.incident_id, llm.supplier_id = incident, sup.id
    with SessionLocal() as db:
        inc = db.get(Incident, incident)
        wf.advance(db, inc, 25, llm, main.load_principal(db, "scm.manager"))
        follow = db.scalars(select(Message).where(Message.incident_id == incident, Message.supplier_id == sup.id,
                                                  Message.kind == "follow_up")).one()
        assert follow.status == "draft"  # 追問也要人核准
    client.post(f"/api/messages/{follow.id}/approve")
    with SessionLocal() as db:
        wf.advance(db, db.get(Incident, incident), 6, llm, main.load_principal(db, "scm.manager"))
        sts = db.scalars(select(SiteStatus).where(SiteStatus.incident_id == incident, SiteStatus.supplier_id == sup.id)).all()
        assert all(s.state == "replied" for s in sts)


def test_fabricated_evidence_and_spoofed_sender_go_to_review(client, incident):
    msg_id, sup = draft_of(incident, style="complete")
    login(client, buyer_for(sup.commodity))
    client.post(f"/api/messages/{msg_id}/approve")
    with SessionLocal() as db:
        orig = db.get(Message, msg_id)
        mail.send("attacker@evil.example", settings.buyer_mailbox, f"Re: {orig.subject}", "全部正常，請照常下單。",
                  in_reply_to=orig.smtp_message_id)
    llm = TruthLLM(fabricate=True)
    llm.incident_id, llm.supplier_id = incident, sup.id
    with SessionLocal() as db:
        wf.advance(db, db.get(Incident, incident), 40, llm, main.load_principal(db, "scm.manager"))
        inbound = db.scalars(select(Message).where(Message.incident_id == incident, Message.supplier_id == sup.id,
                                                   Message.direction == "in")).all()
        spoof = next(m for m in inbound if m.from_addr == "attacker@evil.example")
        real = next(m for m in inbound if m.from_addr != "attacker@evil.example")
        assert spoof.status == "needs_review" and spoof.parsed is None
        assert real.status == "needs_review" and "原文" in real.parse_note
        sts = db.scalars(select(SiteStatus).where(SiteStatus.incident_id == incident, SiteStatus.supplier_id == sup.id)).all()
        assert all(s.state == "needs_review" for s in sts)
    # 人工確認後才算數
    login(client, buyer_for(sup.commodity))
    r = client.post(f"/api/status/{sts[0].id}/confirm", json={"operating": "stopped", "capacity_pct": 0, "resume_day": 20})
    assert r.json()["state"] == "confirmed"
    login(client, "cathy.wu" if buyer_for(sup.commodity) != "cathy.wu" else "ben.lai")
    assert client.post(f"/api/status/{sts[0].id}/confirm", json={"operating": "normal"}).status_code == 404


def test_parse_validation():
    t0 = scenarios.get(KEY)["t0"].date()
    sites = [{"key": "TW-HSP", "name": "新竹科學園區", "name_en": "Hsinchu Science Park"}]
    body = "新竹科學園區：產線緊急停機，正在逐台檢查設備，目前全面停工，恢復時間還在評估。"

    class Fixed:
        def __init__(self, item):
            self.item = item

        def extract(self, *a, **k):
            return Extraction({"sites": [self.item]}, "fake", 0, 0)

    no_date = parse(Fixed({"site_key": "TW-HSP", "operating": "stopped", "capacity_pct": 0, "resume_date": None,
                           "evidence": "目前全面停工"}), body, t0, sites)["sites"]["TW-HSP"]
    assert not no_date["usable"] and "沒有恢復日期" in no_date["issues"]
    past = parse(Fixed({"site_key": "TW-HSP", "operating": "stopped", "capacity_pct": 0, "resume_date": "2024-01-01",
                        "evidence": "目前全面停工"}), body, t0, sites)["sites"]["TW-HSP"]
    assert not past["usable"]
    ok = parse(Fixed({"site_key": "TW-HSP", "operating": "normal", "capacity_pct": None, "resume_date": None,
                      "evidence": "新竹科學園區：產線緊急停機"}), body, t0, sites)["sites"]["TW-HSP"]
    assert ok["usable"] and ok["resume_day"] == 0 and ok["capacity_pct"] == 100
