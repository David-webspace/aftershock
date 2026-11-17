"""風險快報：開案當下主動寄給採購（只列自己負責類別的供應商）與主管（全部），讓人在供應商回覆前就能排優先順序。

這是對內通知，不需要核准；但內容同時列出多家供應商的狀況，所以只能寄到公司內部帳號的信箱，
寄給供應商的那套檢查（不能出現其他供應商名稱）在這裡不適用，改由收件人限制把關。
"""

from collections import defaultdict
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scenarios
from app.config import settings
from app.impact.exposure import Assessment, SiteImpact
from app.models import Incident, Message, Supplier, User
from app.workflow import mail

SENDER = "aftershock@arcwell.example"
COMMODITY = {"semiconductor": "半導體", "passive": "被動元件", "magnetic": "磁性元件", "pcb": "PCB", "mechanical": "機構件",
             "electromechanical": "連接器與機電"}


def mailbox(username: str) -> str:
    return f"{username}@arcwell.example"


def _summaries(db: Session, a: Assessment, by_supplier: dict[str, list[SiteImpact]]) -> list[dict]:
    parts = defaultdict(list)
    for e in a.exposures:
        for sid in {s["supplier_id"] for s in e.sources if s["level"] != "none"}:
            parts[sid].append(e)
    out = []
    for sid, sites in by_supplier.items():
        sup = db.get(Supplier, sid)
        short = [e for e in parts[sid] if e.quake_caused]
        out.append({"id": sid, "name": sup.name, "commodity": sup.commodity, "sites": sites, "short": short,
                    "first_short": min((e.stockout_day for e in short), default=None),
                    "max_mmi": max((s.mmi or 0) for s in sites), "parts": parts[sid]})
    out.sort(key=lambda x: (x["first_short"] is None, x["first_short"] or 0, -x["max_mmi"]))
    return out


def _site_line(s: SiteImpact) -> str:
    return f"{s.site_name}（MMI {s.mmi:.1f}，{s.level.label}）" if s.mmi is not None else f"{s.site_name}（{s.level.label}）"


def _body(inc: Incident, rows: list[dict], drafts: int) -> tuple[str, str]:
    sc = scenarios.get(inc.scenario_key)
    when = sc["t0"].astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y/%m/%d %H:%M")
    short = [r for r in rows if r["short"]]
    subject = f"[AS-{inc.id}] 地震風險快報：{sc['label']}，{len(short)} 家供應商牽涉斷料" if short else \
        f"[AS-{inc.id}] 地震風險快報：{sc['label']}，{len(rows)} 家供應商需要確認"
    lines = [f"{sc['label']}・震央 {sc['place']}・台北時間 {when}", "",
             f"依 USGS 的實際震度，下列 {len(rows)} 家供應商的 {sum(len(r['sites']) for r in rows)} 個廠區可能受影響；"
             f"其中 {len(short)} 家供應的料件會斷料，依最早斷料日排序。", ""]
    if short:
        lines.append("■ 會斷料")
        for i, r in enumerate(short, 1):
            lines.append(f"{i}. {r['name']}（{COMMODITY.get(r['commodity'], r['commodity'])}）")
            lines.append(f"   廠區：{'、'.join(_site_line(s) for s in r['sites'])}")
            for e in sorted(r["short"], key=lambda e: e.stockout_day):
                lines.append(f"   {e.part_no}（{e.category}）：{e.plant} 廠第 {e.stockout_day} 天斷料"
                             + ("，單一來源" if e.single_source else "") + (f"，影響 {len(e.orders_at_risk)} 張客戶訂單" if e.orders_at_risk else ""))
        lines.append("")
    rest = [r for r in rows if not r["short"]]
    if rest:
        lines.append("■ 需要確認（目前推算不會斷料）")
        lines += [f"- {r['name']}：{'、'.join(_site_line(s) for s in r['sites'])}" for r in rest]
        lines.append("")
    lines += [f"詢問信草稿已備好 {drafts} 封，核准後才會寄出；已主動通報的供應商會自動標記。",
              f"應變案：{settings.web_url}/incidents/{inc.id}", "",
              "斷料日依震度對應的規劃停工天數推算；收到供應商回覆或人工確認後，以實際狀況重新計算。",
              "（這封信由 aftershock 自動產生）"]
    return subject, "\n".join(lines)


def send(db: Session, inc: Incident, a: Assessment, by_supplier: dict[str, list[SiteImpact]]) -> int:
    rows = _summaries(db, a, by_supplier)
    if not rows:
        return 0
    sent = 0
    for u in db.scalars(select(User).where(User.role.in_(["buyer", "manager"])).order_by(User.username)):
        mine = rows if u.role == "manager" else [r for r in rows if r["commodity"] in u.commodities]
        if not mine:
            continue
        subject, body = _body(inc, mine, len(mine))  # 每家受影響供應商各有一封詢問信草稿
        # 收件人由帳號推算、不接受外部輸入：快報含多家供應商資訊，只會進內部信箱
        to = mailbox(u.username)
        msg_id = mail.send(SENDER, to, subject, body)
        db.add(Message(incident_id=inc.id, supplier_id=None, direction="out", kind="alert", status="sent", from_addr=SENDER,
                       to_addr=to, subject=subject, body=body, language="zh-TW", token=f"AS-{inc.id}", sim_hour=inc.sim_hours,
                       created_by="system", smtp_message_id=msg_id))
        sent += 1
    return sent
