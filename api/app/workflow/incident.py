"""應變案流程：開案 → 每家受影響供應商一封詢問信草稿 → 採購核准才寄出 → 回信解析 → 狀態回饋曝險 → 逾時追問。

事件時鐘（sim_hours）由畫面推進；模擬供應商依時鐘回信。每個寫入動作都記稽核。
"""

from collections import defaultdict
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app import scenarios
from app.auth import Principal
from app.config import settings
from app.impact.exposure import assess
from app.llm import LLM
from app.models import AuditLog, Contact, Incident, Message, SimReply, SiteStatus, Supplier, Truth, User
from app.sim import supplier as sim
from app.workflow import guard, mail, templates
from app.workflow.parse import parse

FOLLOW_UP_AFTER_HOURS = 24
LANG = {"zh-TW": "zh-TW", "zh-CN": "zh-CN", "ja": "ja"}  # 其他一律英文


def audit(db: Session, user: str | None, event: str, incident_id: int | None, **detail) -> None:
    db.add(AuditLog(username=user, event=event, incident_id=incident_id, detail=detail or None))


def _lang(supplier: Supplier) -> str:
    return LANG.get(supplier.language, "en")


def _token(incident_id: int, supplier_id: str) -> str:
    return f"AS-{incident_id}-{supplier_id}"


def _buyer_for(db: Session, commodity: str) -> User | None:
    return next((u for u in db.scalars(select(User).where(User.role == "buyer")) if commodity in u.commodities), None)


def _sites(db: Session, incident_id: int, supplier_id: str) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        "SELECT ss.site_key AS key, s.name, s.name_en, ss.level FROM site_status ss JOIN sites s ON s.key = ss.site_key "
        "WHERE ss.incident_id = :i AND ss.supplier_id = :s ORDER BY ss.id"), {"i": incident_id, "s": supplier_id}).mappings()]


def _open_parts(db: Session, supplier_id: str, site_keys: list[str]) -> list[dict]:
    rows = db.execute(text("""
        SELECT so.part_no AS pn, COUNT(*) AS n, SUM(po.qty) AS qty FROM purchase_orders po
        JOIN sourcing so ON so.id = po.sourcing_id JOIN supplier_sites ss ON ss.id = so.supplier_site_id
        WHERE ss.supplier_id = :s AND ss.site_key = ANY(:k) AND NOT po.shipped AND po.due_day <= 30
        GROUP BY so.part_no ORDER BY so.part_no"""), {"s": supplier_id, "k": site_keys}).mappings()
    return [{"pn": r["pn"], "n": r["n"], "qty": int(r["qty"])} for r in rows]


def _draft(db: Session, inc: Incident, sup: Supplier, kind: str, author: str | None) -> Message:
    sc = scenarios.get(inc.scenario_key)
    lang = _lang(sup)
    sites = _sites(db, inc.id, sup.id)
    contact = db.scalars(select(Contact).where(Contact.supplier_id == sup.id).order_by(Contact.id)).first()
    buyer = _buyer_for(db, sup.commodity)
    site_names = [s["name"] if lang.startswith("zh") else s["name_en"] for s in sites]
    subject, body = templates.render(
        kind, lang, token=_token(inc.id, sup.id), label=sc["label"] if lang.startswith("zh") else f"M{sc['magnitude']} {sc['place']}",
        contact=contact.name, place=sc["place"], mag=sc["magnitude"], event_date=sc["t0"].date(), sites=site_names,
        parts=_open_parts(db, sup.id, [s["key"] for s in sites]), buyer=buyer.name if buyer else "Procurement")
    msg = Message(incident_id=inc.id, supplier_id=sup.id, direction="out", kind=kind, status="draft", from_addr=settings.buyer_mailbox,
                  to_addr=contact.email, subject=subject, body=body, language=lang, token=_token(inc.id, sup.id), sim_hour=inc.sim_hours,
                  created_by=author)
    msg.guard_issues = guard.check(db, sup.id, msg.to_addr, subject, body)
    db.add(msg)
    return msg


def open_incident(db: Session, scenario_key: str, user: Principal) -> Incident:
    a = assess(db, scenario_key)
    inc = Incident(scenario_key=scenario_key, created_by=user.username, sim_hours=0, status="open")
    db.add(inc)
    db.flush()
    used = {s["supplier_site_id"] for e in a.exposures for s in e.sources}
    by_supplier = defaultdict(list)
    for site in a.sites:
        if site.level.rank == 0:
            continue
        for s in site.suppliers:
            if s["supplier_site_id"] in used:
                by_supplier[s["supplier_id"]].append(site)
    for supplier_id, sites in sorted(by_supplier.items()):
        for site in sites:
            db.add(SiteStatus(incident_id=inc.id, supplier_id=supplier_id, site_key=site.site_key, level=site.level.key, mmi=site.mmi))
            db.add(Truth(incident_id=inc.id, supplier_id=supplier_id, site_key=site.site_key,
                         **sim.truth(scenario_key, supplier_id, site.site_key, site.level.key)))
        db.flush()
        _draft(db, inc, db.get(Supplier, supplier_id), "inquiry", None)
    audit(db, user.username, "incident_open", inc.id, scenario=scenario_key, suppliers=len(by_supplier))
    db.commit()
    return inc


def visible_message(db: Session, msg_id: int, user: Principal) -> tuple[Message, Supplier]:
    msg = db.get(Message, msg_id)
    sup = db.get(Supplier, msg.supplier_id) if msg else None
    # 不是自己負責的料件類別：當成不存在（回 404），不透露有這封信
    if msg is None or not (user.role == "manager" or (user.role == "buyer" and user.handles(sup.commodity))):
        raise HTTPException(404, "找不到這封信")
    return msg, sup


def edit_draft(db: Session, msg_id: int, user: Principal, body: str) -> Message:
    msg, _ = visible_message(db, msg_id, user)
    if msg.status != "draft":
        raise HTTPException(409, "只能修改草稿")
    msg.body = body
    msg.guard_issues = guard.check(db, msg.supplier_id, msg.to_addr, msg.subject, body)
    audit(db, user.username, "draft_edit", msg.incident_id, message_id=msg.id)
    db.commit()
    return msg


def approve(db: Session, msg_id: int, user: Principal) -> Message:
    msg, sup = visible_message(db, msg_id, user)
    if msg.status != "draft":
        raise HTTPException(409, "這封信已經處理過")
    # 核准當下再檢查一次：草稿可能在建立後被改過，聯絡人資料也可能變動
    issues = guard.check(db, msg.supplier_id, msg.to_addr, msg.subject, msg.body)
    msg.guard_issues = issues
    if issues:
        db.commit()
        raise HTTPException(422, "；".join(issues))
    inc = db.get(Incident, msg.incident_id)
    msg.smtp_message_id = mail.send(msg.from_addr, msg.to_addr, msg.subject, msg.body)
    msg.status, msg.approved_by, msg.sim_hour = "sent", user.username, inc.sim_hours
    db.execute(update(SiteStatus).where(SiteStatus.incident_id == inc.id, SiteStatus.supplier_id == sup.id,
                                        SiteStatus.state.in_(["pending", "no_reply"])).values(state="inquired"))
    _schedule_reply(db, inc, sup, msg)
    audit(db, user.username, f"{msg.kind}_sent", inc.id, message_id=msg.id, supplier=sup.id, to=msg.to_addr)
    db.commit()
    return msg


def reject(db: Session, msg_id: int, user: Principal) -> Message:
    msg, _ = visible_message(db, msg_id, user)
    if msg.status != "draft":
        raise HTTPException(409, "這封信已經處理過")
    msg.status = "rejected"
    audit(db, user.username, "draft_rejected", msg.incident_id, message_id=msg.id)
    db.commit()
    return msg


def _schedule_reply(db: Session, inc: Incident, sup: Supplier, msg: Message) -> None:
    style = sim.style(inc.scenario_key, sup.id)
    if msg.kind == "follow_up":
        style = "complete"  # 被追問後完整回覆
    elif style == "silent":
        return
    truths = db.scalars(select(Truth).where(Truth.incident_id == inc.id, Truth.supplier_id == sup.id)).all()
    worst = "stopped" if any(t.operating == "stopped" for t in truths) else ("partial" if any(t.operating == "partial" for t in truths) else "normal")
    due = inc.sim_hours + (sim.delay_hours(inc.scenario_key, sup.id, worst) if msg.kind == "inquiry" else 4)
    db.add(SimReply(incident_id=inc.id, supplier_id=sup.id, reply_to_message_id=msg.id, due_hour=due, style=style))


def advance(db: Session, inc: Incident, hours: int, llm: LLM | None, user: Principal) -> dict:
    """推進事件時鐘：寄出到期的模擬回信 → 收信、解析 → 逾時沒有可用回覆的供應商產生追問草稿。"""
    inc.sim_hours += hours
    delivered = _deliver_replies(db, inc)
    received = process_inbox(db, inc, llm)
    followups = _draft_followups(db, inc)
    audit(db, user.username, "clock_advance", inc.id, hours=hours, delivered=delivered, received=received, followups=followups)
    db.commit()
    return {"sim_hours": inc.sim_hours, "delivered": delivered, "received": received, "followups": followups}


def _deliver_replies(db: Session, inc: Incident) -> int:
    sc = scenarios.get(inc.scenario_key)
    due = db.scalars(select(SimReply).where(SimReply.incident_id == inc.id, ~SimReply.delivered, SimReply.due_hour <= inc.sim_hours)
                     .order_by(SimReply.due_hour)).all()
    for r in due:
        sup = db.get(Supplier, r.supplier_id)
        orig = db.get(Message, r.reply_to_message_id)
        contact = db.scalars(select(Contact).where(Contact.email == orig.to_addr)).first()
        lang = _lang(sup)
        sites = []
        for s in _sites(db, inc.id, sup.id):
            t = db.get(Truth, (inc.id, sup.id, s["key"]))
            sites.append((s["name"] if lang.startswith("zh") else s["name_en"],
                          {"operating": t.operating, "capacity_pct": t.capacity_pct, "resume_day": t.resume_day, "damage": t.damage}))
        variant = int(sup.id[-1]) % 2
        body = sim.reply_body(lang, contact.name, r.style, sites, sc["t0"].date(), variant)
        _send_reply(contact.email, orig, body)
        r.delivered = True
    return len(due)


def _send_reply(from_addr: str, orig: Message, body: str) -> None:
    # 模擬供應商回信：寄到採購信箱（同樣是 .example 網域，只會進 Mailpit）
    mail.send(from_addr, settings.buyer_mailbox, f"Re: {orig.subject}", body, in_reply_to=orig.smtp_message_id)


def process_inbox(db: Session, inc: Incident, llm: LLM | None) -> int:
    sc = scenarios.get(inc.scenario_key)
    seen = set(db.scalars(select(Message.mailpit_id).where(Message.mailpit_id.is_not(None))))
    count = 0
    for m in mail.inbox(settings.buyer_mailbox):
        if m["mailpit_id"] in seen:
            continue
        orig = db.scalars(select(Message).where(Message.smtp_message_id == m["in_reply_to"])).first() if m["in_reply_to"] else None
        if orig is None or orig.incident_id != inc.id:
            continue
        sup = db.get(Supplier, orig.supplier_id)
        msg = Message(incident_id=inc.id, supplier_id=sup.id, direction="in", kind="reply", status="received", from_addr=m["from"],
                      to_addr=settings.buyer_mailbox, subject=m["subject"], body=m["body"], language=orig.language, token=orig.token,
                      sim_hour=inc.sim_hours, smtp_message_id=m["message_id"], in_reply_to=m["in_reply_to"], mailpit_id=m["mailpit_id"])
        db.add(msg)
        db.flush()
        count += 1
        # 寄件人必須是這家供應商登記的聯絡人：冒名的信不解析、不採信，交人處理
        registered = set(db.scalars(select(Contact.email).where(Contact.supplier_id == sup.id)))
        if m["from"] not in registered:
            msg.status, msg.parse_note = "needs_review", "寄件人不是這家供應商登記的聯絡人，未解析"
            continue
        if llm is None:
            msg.status, msg.parse_note = "needs_review", "尚未設定模型，請人工判讀"
            continue
        sites = _sites(db, inc.id, sup.id)
        result = parse(llm, m["body"], sc["t0"].date(), sites)
        msg.parsed = result
        _apply(db, inc, sup.id, msg, result)
    return count


def _apply(db: Session, inc: Incident, supplier_id: str, msg: Message, result: dict) -> None:
    all_ok = bool(result["sites"]) and not result["issues"]
    for key, r in result["sites"].items():
        st = db.scalars(select(SiteStatus).where(SiteStatus.incident_id == inc.id, SiteStatus.supplier_id == supplier_id,
                                                 SiteStatus.site_key == key)).one()
        if st.state == "confirmed":
            continue  # 人工確認過的不被後來的解析覆蓋
        st.operating, st.capacity_pct, st.resume_day, st.damage = r["operating"], r["capacity_pct"], r["resume_day"], r["damage"]
        st.source_message_id = msg.id
        st.state = "replied" if r["usable"] else "needs_review"
        all_ok = all_ok and r["usable"]
    msg.status = "parsed" if all_ok else "needs_review"
    msg.parse_note = "；".join(result["issues"] + [f"{k}：{'、'.join(r['issues'])}" for k, r in result["sites"].items() if r["issues"]]) or None


def _draft_followups(db: Session, inc: Incident) -> int:
    n = 0
    for sup_id in db.scalars(select(SiteStatus.supplier_id).where(SiteStatus.incident_id == inc.id).distinct()):
        statuses = db.scalars(select(SiteStatus).where(SiteStatus.incident_id == inc.id, SiteStatus.supplier_id == sup_id)).all()
        if all(s.state in ("replied", "confirmed") for s in statuses):
            continue
        outs = db.scalars(select(Message).where(Message.incident_id == inc.id, Message.supplier_id == sup_id, Message.direction == "out")
                          .order_by(Message.id.desc())).all()
        if not outs or outs[0].status != "sent":
            continue
        if inc.sim_hours - outs[0].sim_hour < FOLLOW_UP_AFTER_HOURS:
            continue
        for s in statuses:
            if s.state == "inquired":
                s.state = "no_reply"
        _draft(db, inc, db.get(Supplier, sup_id), "follow_up", None)
        n += 1
    return n


def confirm_status(db: Session, status_id: int, user: Principal, operating: str, capacity_pct: int | None, resume_day: int | None) -> SiteStatus:
    st = db.get(SiteStatus, status_id)
    sup = db.get(Supplier, st.supplier_id) if st else None
    if st is None or not (user.role == "manager" or (user.role == "buyer" and user.handles(sup.commodity))):
        raise HTTPException(404, "找不到這筆狀態")
    if operating not in ("normal", "partial", "stopped"):
        raise HTTPException(400, "狀態只能是正常、部分運作或停工")
    if operating != "normal" and (resume_day is None or not 0 <= resume_day <= 365):
        raise HTTPException(400, "停工或部分運作時，請填 0～365 天內的恢復日")
    st.operating, st.capacity_pct = operating, 100 if operating == "normal" else (0 if operating == "stopped" else capacity_pct)
    st.resume_day, st.state, st.confirmed_by = 0 if operating == "normal" else resume_day, "confirmed", user.username
    audit(db, user.username, "status_confirmed", st.incident_id, status_id=st.id, operating=operating, resume_day=st.resume_day)
    db.commit()
    return st


def overrides(db: Session, inc: Incident) -> dict[str, int]:
    """已回覆或人工確認的狀態 → 各供應商廠區的停工天數，取代規劃假設。部分運作以「恢復日 ×（1－產能）」近似。"""
    out = {}
    rows = db.execute(text("""
        SELECT ss.id AS ssid, st.operating, st.capacity_pct, st.resume_day FROM site_status st
        JOIN supplier_sites ss ON ss.supplier_id = st.supplier_id AND ss.site_key = st.site_key
        WHERE st.incident_id = :i AND st.state IN ('replied', 'confirmed')"""), {"i": inc.id}).mappings()
    for r in rows:
        if r["operating"] == "normal":
            out[r["ssid"]] = 0
        elif r["operating"] == "stopped":
            out[r["ssid"]] = r["resume_day"]
        else:
            out[r["ssid"]] = round(r["resume_day"] * (1 - (r["capacity_pct"] or 0) / 100))
    return out


def sim_date(inc: Incident):
    return scenarios.get(inc.scenario_key)["t0"] + timedelta(hours=inc.sim_hours)
