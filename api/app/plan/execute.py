"""主管選定方案 → 依動作產生信件草稿（一律要人核准才寄出）。

- 追加訂單 → 給該供應商（其語言），列出各廠的料號、數量、運輸方式、希望出貨日。這是「請求確認」，
  正式訂單在供應商確認後才於 ERP 開立；信中數量即為對外承諾，只能是方案中的數字（寄信防護會檢查）。
- 調撥 → 內部通知調出廠的物料單位
- 啟用備援來源 → 內部通知工程單位安排認證
"""

from collections import defaultdict
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scenarios
from app.auth import Principal
from app.config import settings
from app.impact.exposure import assess
from app.models import Contact, Incident, Message, PlanDecision, Supplier
from app.plan import assumptions as A
from app.plan.explain import explain
from app.plan.options import options
from app.plan.solver import HORIZON
from app.workflow import guard
from app.workflow.incident import LANG, _buyer_for, audit, overrides

MODE = {"zh-TW": {"sea": "海運", "air": "空運", "truck": "陸運"}, "zh-CN": {"sea": "海运", "air": "空运", "truck": "陆运"},
        "ja": {"sea": "海上輸送", "air": "航空輸送", "truck": "陸送"}, "en": {"sea": "sea", "air": "air", "truck": "truck"}}
HEAD = {
    "zh-TW": ("[{token}] 追加出貨請求確認", "{contact} 您好：\n\n因地震影響部分來源供貨，想請貴司協助以下追加出貨（數量依貴司先前提供的產能估算）。請確認是否可配合，確認後我們會開立正式訂單：\n"),
    "zh-CN": ("[{token}] 追加出货请求确认", "{contact} 您好：\n\n因地震影响部分来源供货，想请贵司协助以下追加出货（数量依贵司先前提供的产能估算）。请确认是否可配合，确认后我们会开立正式订单：\n"),
    "ja": ("[{token}] 追加出荷のご相談", "{contact} 様\n\n地震により一部の調達先からの供給に影響が出ているため、下記の追加出荷についてご協力をお願いできないでしょうか（数量は貴社の生産能力を基に試算しております）。可否をご確認いただけましたら、正式な注文書を発行いたします。\n"),
    "en": ("[{token}] Request to confirm additional shipments", "Dear {contact},\n\nAs some of our supply is affected by the earthquake, could you support the additional shipments below (quantities are based on your available capacity)? Please confirm whether this is possible; we will issue formal purchase orders once confirmed.\n"),
}
LINE = {"zh-TW": "- {pn} → {plant}：{qty} 個，{mode}，希望 {ship} 出貨", "zh-CN": "- {pn} → {plant}：{qty} 个，{mode}，希望 {ship} 出货",
        "ja": "- {pn} → {plant}：{qty} 個、{mode}、{ship} 出荷希望", "en": "- {pn} → {plant}: {qty} pcs, {mode}, ship by {ship}"}
TAIL = {"zh-TW": "\n謝謝！\n\nArcwell Electronics 採購部\n{buyer}", "zh-CN": "\n谢谢！\n\nArcwell Electronics 采购部\n{buyer}",
        "ja": "\n何卒よろしくお願い申し上げます。\n\nArcwell Electronics 購買部\n{buyer}", "en": "\nThank you.\n\nBest regards,\n{buyer}\nProcurement, Arcwell Electronics"}
PLANT_NAME = {"TW1": "Taoyuan (TW1)", "CN1": "Dongguan (CN1)", "TH1": "Ayutthaya (TH1)", "VN1": "Bac Ninh (VN1)"}


def current_options(db: Session, inc: Incident, llm=None) -> dict:
    """預設不呼叫模型：比較說明由程式產生（見 explain.py 的理由）。"""
    a = assess(db, inc.scenario_key, horizon=HORIZON, outage_overrides=overrides(db, inc))
    opts = options(db, a)
    opts["explanation"] = explain(llm, opts)
    return opts


def choose(db: Session, inc: Incident, profile: str, user: Principal, llm) -> PlanDecision:
    opts = current_options(db, inc, llm)
    chosen = next((o for o in opts["options"] if o["key"] == profile), None)
    if chosen is None:
        raise HTTPException(400, "沒有這個方案")
    decision = PlanDecision(incident_id=inc.id, profile=profile, snapshot=opts, explanation=opts["explanation"], decided_by=user.username)
    db.add(decision)
    db.flush()
    t0 = scenarios.get(inc.scenario_key)["t0"].date()
    by_supplier = defaultdict(list)
    transfers, alts = [], []
    for plan in chosen["plans"]:
        for act in plan["actions"]:
            if act["type"] == "extra_order":
                by_supplier[act["supplier_id"]] += [(plan["part_no"], act["mode"], lot) for lot in act["lots"]]
            elif act["type"] == "transfer":
                transfers.append((plan["part_no"], act))
            else:
                alts.append((plan["part_no"], act))
    for supplier_id, lots in sorted(by_supplier.items()):
        sup = db.get(Supplier, supplier_id)
        lang = LANG.get(sup.language, "en")
        contact = db.scalars(select(Contact).where(Contact.supplier_id == sup.id).order_by(Contact.id)).first()
        buyer = _buyer_for(db, sup.commodity)
        token = f"AS-{inc.id}-{sup.id}-P{decision.id}"
        subject, intro = HEAD[lang]
        lines = [LINE[lang].format(pn=pn, plant=PLANT_NAME[lot["plant"]], qty=f"{lot['qty']:,}", mode=MODE[lang][mode],
                                   ship=(t0 + timedelta(days=lot["order_day"] + A.EXTRA_ORDER_PREP_DAYS)).isoformat())
                 for pn, mode, lot in sorted(lots, key=lambda x: (x[0], x[2]["order_day"]))]
        body = intro.format(contact=contact.name) + "\n".join(lines) + TAIL[lang].format(buyer=buyer.name if buyer else "Procurement")
        _add(db, inc, decision, sup.id, "expedite", contact.email, subject.format(token=token), body, lang, token,
             [lot["qty"] for _, _, lot in lots], user)
    for pn, act in transfers:
        token = f"AS-{inc.id}-T{decision.id}"
        body = (f"{act['from']} 物料單位您好：\n\n依地震應變方案，請將 {pn} 調撥至 {act['plant']}：\n"
                + "\n".join(f"- {(t0 + timedelta(days=lot['order_day'])).isoformat()} 出貨 {lot['qty']:,} 個，預計 "
                            f"{(t0 + timedelta(days=lot['arrive_day'])).isoformat()} 到" for lot in act["lots"])
                + f"\n\n調出後貴廠仍保留至少 {A.TRANSFER_KEEP_DAYS} 天用量。\n\n供應鏈管理部")
        _add(db, inc, decision, None, "transfer", f"{act['from'].lower()}.materials@arcwell.example",
             f"[{token}] 庫存調撥：{pn} {act['from']}→{act['plant']}", body, "zh-TW", token,
             [lot["qty"] for lot in act["lots"]] + [A.TRANSFER_KEEP_DAYS], user)
    for pn, act in alts:
        token = f"AS-{inc.id}-Q{decision.id}"
        body = (f"工程部您好：\n\n依地震應變方案，請啟動 {act['supplier']} 的 {pn} 認證，目標 {A.QUALIFICATION_DAYS} 天內完成；"
                f"認證後預計採購 {act['qty']:,} 個。\n\n供應鏈管理部")
        _add(db, inc, decision, None, "qualify", "engineering@arcwell.example", f"[{token}] 備援來源認證：{pn}", body, "zh-TW", token,
             [act["qty"], A.QUALIFICATION_DAYS], user)
    audit(db, user.username, "plan_chosen", inc.id, plan_id=decision.id, profile=profile, cost_usd=chosen["cost_usd"],
          shortage_units=chosen["shortage_units"])
    db.commit()
    return decision


def _add(db, inc, decision, supplier_id, kind, to_addr, subject, body, lang, token, allowed, user) -> None:
    msg = Message(incident_id=inc.id, supplier_id=supplier_id, direction="out", kind=kind, status="draft",
                  from_addr=settings.buyer_mailbox, to_addr=to_addr, subject=subject, body=body, language=lang, token=token,
                  sim_hour=inc.sim_hours, created_by=user.username, plan_id=decision.id, allowed_numbers=sorted(set(allowed)))
    msg.guard_issues = guard.check(db, supplier_id, to_addr, subject, body, msg.allowed_numbers)
    db.add(msg)
