"""aftershock API。權限一律依登入身分在伺服器端判斷：採購只看得到自己負責料件類別的供應商往來。"""

import logging
import threading
import time
from contextlib import asynccontextmanager

import httpx

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import scenarios
from app.auth import COOKIE, LOGIN_FAILED, Principal, authenticate, current_principal, issue_token, load_principal, require_role
from app.config import settings
from app.db import SessionLocal, engine, get_db
from app.impact.exposure import assess
from app.ingest import usgs
from app.llm import get_llm, not_configured
from app.models import AuditLog, Incident
from app.ratelimit import SlidingWindow
from app.plan import execute
from app.workflow import alert
from app.workflow import incident as wf

log = logging.getLogger("aftershock")


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = threading.Event()
    if settings.auto_detect_minutes > 0:
        threading.Thread(target=_auto_detect_loop, args=(stop,), daemon=True, name="auto-detect").start()
    yield
    stop.set()


app = FastAPI(title="aftershock", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
login_limit = SlidingWindow(10, 300)
WORKERS = ("buyer", "manager")


@app.get("/health")
def health() -> dict:
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


class LoginIn(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


def me_view(p: Principal) -> dict:
    return {"username": p.username, "name": p.name, "role": p.role, "role_label": p.role_label, "commodities": list(p.commodities)}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    login_limit.check(f"{request.client.host if request.client else '-'}:{body.username}")
    username = authenticate(db, body.username.strip(), body.password)
    if username is None:
        wf.audit(db, None, "login_failed", None, username=body.username[:32])
        db.commit()
        raise HTTPException(401, LOGIN_FAILED)
    response.set_cookie(COOKIE, issue_token(username), httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.jwt_ttl_hours * 3600)
    return me_view(load_principal(db, username))


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(p: Principal = Depends(current_principal)) -> dict:
    return me_view(p)


@app.get("/api/scenarios")
def scenario_list(_: Principal = Depends(require_role(*WORKERS))) -> list[dict]:
    out = []
    for key in scenarios.all_scenarios():
        s = scenarios.get(key)
        out.append({"key": key, "label": s["label"], "note": s["note"], "magnitude": s["magnitude"], "place": s["place"],
                    "t0": s["t0"].isoformat(), "max_mmi": s["max_mmi"], "usgs_url": s["url"]})
    return out


class OpenIn(BaseModel):
    scenario: str = Field(max_length=32)


@app.post("/api/incidents")
def incident_open(body: OpenIn, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    if not scenarios.is_valid(body.scenario):
        raise HTTPException(400, "沒有這個情境")
    try:
        scenarios.get(body.scenario)
    except (KeyError, httpx.HTTPError):
        # 即時事件可能還沒有 ShakeMap（通常震後數分鐘到一小時才發布），沒有震度資料就無法判斷影響
        raise HTTPException(409, "USGS 尚未發布這起地震的震度資料（ShakeMap），請稍後再試")
    return {"id": wf.open_incident(db, body.scenario, p).id}


@app.get("/api/incidents")
def incident_list(_: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Incident).order_by(Incident.id.desc()).limit(50)).all()
    return [{"id": i.id, "scenario": i.scenario_key, "label": scenarios.get(i.scenario_key)["label"], "status": i.status,
             "sim_hours": i.sim_hours, "created_at": i.created_at.isoformat(), "created_by": i.created_by, "source": i.source} for i in rows]


def _incident(db: Session, incident_id: int) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, "找不到這個應變案")
    return inc


def _commodity_filter(p: Principal) -> tuple[str, dict]:
    # 分工寫進 SQL：採購只撈得到自己負責類別的供應商
    if p.role == "manager":
        return "", {}
    return " AND sp.commodity = ANY(:commodities)", {"commodities": list(p.commodities)}


@app.get("/api/incidents/{incident_id}")
def incident_detail(incident_id: int, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    inc = _incident(db, incident_id)
    sc = scenarios.get(inc.scenario_key)
    a = assess(db, inc.scenario_key, outage_overrides=wf.overrides(db, inc))
    cond, params = _commodity_filter(p)
    statuses = [dict(r) for r in db.execute(text(f"""
        SELECT st.id, st.supplier_id, sp.name AS supplier, sp.commodity, st.site_key, s.name AS site, s.lat, s.lon, st.level, st.mmi,
               st.state, st.operating, st.capacity_pct, st.resume_day, st.damage, st.confirmed_by
        FROM site_status st JOIN suppliers sp ON sp.id = st.supplier_id JOIN sites s ON s.key = st.site_key
        WHERE st.incident_id = :i{cond} ORDER BY st.mmi DESC NULLS LAST, sp.name"""), {"i": inc.id, **params}).mappings()]
    risky = [e for e in a.exposures if e.quake_caused]
    return {
        "id": inc.id, "sim_hours": inc.sim_hours, "now": wf.sim_date(inc).isoformat(), "status": inc.status,
        "scenario": {"key": inc.scenario_key, "label": sc["label"], "magnitude": sc["magnitude"], "place": sc["place"],
                     "lat": sc["lat"], "lon": sc["lon"], "t0": sc["t0"].isoformat(), "max_mmi": sc["max_mmi"], "usgs_url": sc["url"]},
        "sites": [{"key": s.site_key, "name": s.site_name, "lat": s.lat, "lon": s.lon, "mmi": s.mmi, "pga_g": s.pga_g, "level": s.level.key,
                   "level_label": s.level.label, "suppliers": len(s.suppliers), "plants": s.plants} for s in a.sites if s.level.rank > 0],
        "statuses": statuses,
        "exposure": {"checked": len(a.exposures), "stockouts": [
            {"plant": e.plant, "part_no": e.part_no, "category": e.category, "level": e.level.label, "single_source": e.single_source,
             "impacted_share_pct": e.impacted_share_pct, "cover_days": e.cover_days, "stockout_day": e.stockout_day,
             "orders_at_risk": len(e.orders_at_risk), "order_qty_at_risk": sum(o["qty"] for o in e.orders_at_risk)} for e in risky]},
        "model_ready": not_configured() is None,
        "plan": _latest_plan(db, inc.id),
    }


def _latest_plan(db: Session, incident_id: int) -> dict | None:
    d = db.execute(text("SELECT profile, decided_by, decided_at FROM plan_decisions WHERE incident_id = :i ORDER BY id DESC LIMIT 1"),
                   {"i": incident_id}).mappings().first()
    return {"profile": d["profile"], "decided_by": d["decided_by"], "decided_at": d["decided_at"].isoformat()} if d else None


@app.get("/api/incidents/{incident_id}/messages")
def messages(incident_id: int, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> list[dict]:
    _incident(db, incident_id)
    cond, params = _commodity_filter(p)
    if cond:
        # 採購另外看得到寄給自己的風險快報
        cond, params = f" AND ({cond[5:]} OR (m.kind = 'alert' AND m.to_addr = :mine))", {**params, "mine": alert.mailbox(p.username)}
    rows = db.execute(text(f"""
        SELECT m.id, m.supplier_id, sp.name AS supplier, sp.commodity, m.direction, m.kind, m.status, m.from_addr, m.to_addr,
               m.subject, m.body, m.language, m.sim_hour, m.approved_by, m.guard_issues, m.parsed, m.parse_note, m.plan_id
        FROM messages m LEFT JOIN suppliers sp ON sp.id = m.supplier_id WHERE m.incident_id = :i{cond} ORDER BY m.id"""),
                      {"i": incident_id, **params}).mappings()
    return [dict(r) for r in rows]


class EditIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


@app.patch("/api/messages/{msg_id}")
def message_edit(msg_id: int, body: EditIn, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    m = wf.edit_draft(db, msg_id, p, body.body)
    return {"id": m.id, "guard_issues": m.guard_issues}


@app.post("/api/messages/{msg_id}/approve")
def message_approve(msg_id: int, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    m = wf.approve(db, msg_id, p)
    return {"id": m.id, "status": m.status}


@app.post("/api/messages/{msg_id}/reject")
def message_reject(msg_id: int, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    return {"id": wf.reject(db, msg_id, p).id, "status": "rejected"}


class AdvanceIn(BaseModel):
    hours: int = Field(ge=1, le=72)


@app.post("/api/incidents/{incident_id}/advance")
def advance(incident_id: int, body: AdvanceIn, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    inc = _incident(db, incident_id)
    return wf.advance(db, inc, body.hours, None if not_configured() else get_llm(), p)


class ConfirmIn(BaseModel):
    operating: str
    capacity_pct: int | None = Field(None, ge=0, le=100)
    resume_day: int | None = Field(None, ge=0, le=365)


@app.post("/api/status/{status_id}/confirm")
def status_confirm(status_id: int, body: ConfirmIn, p: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    st = wf.confirm_status(db, status_id, p, body.operating, body.capacity_pct, body.resume_day)
    return {"id": st.id, "state": st.state}


@app.get("/api/admin/audit")
def audit_log(_: Principal = Depends(require_role("sysadmin")), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(300)).all()
    return [{"ts": r.ts.isoformat(), "username": r.username, "event": r.event, "incident_id": r.incident_id, "detail": r.detail} for r in rows]



# ── 補救方案 ─────────────────────────────────────────────


@app.get("/api/incidents/{incident_id}/options")
def plan_options(incident_id: int, _: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    inc = _incident(db, incident_id)
    return execute.current_options(db, inc)


class ChooseIn(BaseModel):
    profile: str = Field(max_length=16)


@app.post("/api/incidents/{incident_id}/plan")
def plan_choose(incident_id: int, body: ChooseIn, p: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)) -> dict:
    # 選方案會產生對外承諾（追加數量）與內部調撥，只有主管能決定
    inc = _incident(db, incident_id)
    # 快照存固定格式的說明即可；模型說明只在比較方案時顯示，不重複呼叫
    d = execute.choose(db, inc, body.profile, p, None)
    return {"plan_id": d.id, "profile": d.profile}


# ── 地圖與即時地震 ─────────────────────────────────────────


@app.get("/api/incidents/{incident_id}/contours")
def contours(incident_id: int, _: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> Response:
    sc = scenarios.get(_incident(db, incident_id).scenario_key)
    path = usgs._dir(sc["event_id"]) / "cont_mmi.json"
    return Response(path.read_bytes(), media_type="application/json")


@app.get("/api/map/sites")
def map_sites(_: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(text("""
        SELECT s.key, s.name, s.country, s.lat, s.lon, s.precision, COUNT(DISTINCT ss.supplier_id) AS suppliers,
               STRING_AGG(DISTINCT p.key, ',') AS plants
        FROM sites s LEFT JOIN supplier_sites ss ON ss.site_key = s.key LEFT JOIN plants p ON p.site_key = s.key
        GROUP BY s.key HAVING COUNT(ss.id) > 0 OR COUNT(p.key) > 0 ORDER BY s.key""")).mappings()
    return [{**dict(r), "plants": r["plants"].split(",") if r["plants"] else []} for r in rows]


_live_cache: dict = {"at": 0.0, "data": None}
_live_lock = threading.Lock()
LIVE_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
AUTO_MAX_AGE_HOURS = 48


def _feed() -> dict:
    """USGS 最近 7 天規模 4.5 以上的地震。快取 5 分鐘，避免每次開頁都打 USGS。"""
    with _live_lock:
        if _live_cache["data"] is None or time.time() - _live_cache["at"] > 300:
            _live_cache.update(at=time.time(), data=httpx.get(LIVE_FEED, timeout=15).raise_for_status().json())
        return _live_cache["data"]


def _our_sites(db: Session) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        "SELECT DISTINCT s.key, s.name, s.lat, s.lon FROM sites s LEFT JOIN supplier_sites ss ON ss.site_key = s.key "
        "LEFT JOIN plants p ON p.site_key = s.key WHERE ss.id IS NOT NULL OR p.key IS NOT NULL")).mappings()]


def _nearby(feed: dict, sites: list[dict]) -> list[tuple[dict, list]]:
    out = []
    for f in feed["features"]:
        lon, lat, _ = f["geometry"]["coordinates"]
        near = sorted(((_km(lat, lon, s["lat"], s["lon"]), s["name"]) for s in sites))[:3]
        if near and near[0][0] <= 500:
            out.append((f, near))
    return out


@app.get("/api/live")
def live(_: Principal = Depends(require_role(*WORKERS)), db: Session = Depends(get_db)) -> dict:
    """離我們供應商或工廠 500 公里內的即時地震；已經開案的附上案號。"""
    try:
        feed = _feed()
    except httpx.HTTPError:
        log.exception("USGS feed unavailable")
        return {"events": [], "error": "暫時連不上 USGS 即時資料"}
    opened = dict(db.execute(text("SELECT scenario_key, MIN(id) FROM incidents WHERE scenario_key LIKE 'usgs:%' GROUP BY scenario_key")).all())
    events = []
    for f, near in _nearby(feed, _our_sites(db)):
        p = f["properties"]
        events.append({"id": f["id"], "magnitude": p["mag"], "place": p["place"], "time": p["time"], "depth_km": f["geometry"]["coordinates"][2],
                       "shakemap": "shakemap" in (p.get("types") or ""), "url": p["url"], "incident_id": opened.get(f"usgs:{f['id']}"),
                       "nearest": [{"site": n, "km": round(d)} for d, n in near]})
    return {"events": sorted(events, key=lambda e: -e["time"])[:20], "error": None,
            "auto_detect_minutes": settings.auto_detect_minutes}


def auto_detect_once() -> list[int]:
    """近 48 小時、有 ShakeMap、離我們 500 公里內的地震：任一受影響供應商廠區達到「需要確認」就開案（同一起地震只開一次）。"""
    opened = []
    with SessionLocal() as db:
        for f, _ in _nearby(_feed(), _our_sites(db)):
            p = f["properties"]
            key = f"usgs:{f['id']}"
            if ("shakemap" not in (p.get("types") or "") or time.time() - p["time"] / 1000 > AUTO_MAX_AGE_HOURS * 3600
                    or not scenarios.is_valid(key) or db.scalar(select(Incident.id).where(Incident.scenario_key == key).limit(1))):
                continue
            try:
                a = assess(db, key)
            except (KeyError, httpx.HTTPError):
                continue  # ShakeMap 還沒處理完，下一輪再試
            if wf.affected_suppliers(a):
                opened.append(wf.open_incident(db, key, None, a).id)
    return opened


def _auto_detect_loop(stop: threading.Event) -> None:
    while True:
        try:
            if ids := auto_detect_once():
                log.info("auto-detect opened incidents %s", ids)
        except Exception:
            log.exception("auto-detect failed")  # 背景執行緒：連不上 USGS 等錯誤只記錄，下一輪再試
        if stop.wait(settings.auto_detect_minutes * 60):
            return


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    a = sin(radians(lat2 - lat1) / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))
