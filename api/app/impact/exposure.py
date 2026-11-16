"""曝險計算：某起地震對我們每座工廠、每個料件的影響。全部是確定性計算，模型不參與。

規格（評測的標準答案 app/evals/oracle.py 依同一份規格另外實作）：

1. 廠區影響：每個供應商廠區與自有工廠依所在座標取 ShakeMap 震度，套 rules.level_for 得到等級與規劃停工天數 O。
   outage_overrides 以「供應商廠區」為單位覆寫停工天數（收到供應商回覆或人工確認後，用實際狀況取代規劃假設）。
2. 受影響的「工廠 × 料件」：該料件任一合格來源的廠區等級 ≥「需要確認」。週用量 W＝Σ 成品週需求 × BOM 用量，日用量 d＝W／7。
3. 供給推估（第 1～H 天）：
   - 每個來源的「批次」＝既有採購單＋尚未下的單（最後一張採購單之後每 7 天一批 W×分配比例，運輸天數同該來源）。
   - 已出貨的在途批次照原交期到貨（逾期的視為第 1 天到）。來源沒停工時，未出貨批次也照原交期。
   - 來源停工 O 天：未出貨批次依原交期順序排隊，第 O 天起以該廠分到的產能（週產能 × 本廠用量占比 ÷ 7，每天）
     逐批生產，完成後加上運輸天數到貨，但不早於原交期。到貨晚於原交期的批次數量計入「延誤量」。
   - 第 t 天庫存＝現有庫存＋到貨累計－d×t；第一個小於 0 的 t 為斷料日。
   - 同樣算一次「沒有地震」的基準斷料日；斷料日早於基準（或基準不會斷料）才算地震造成。
4. 受影響的客戶訂單：該廠使用此料件的成品中，交期在斷料日當天或之後的訂單。
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import scenarios
from app.impact.rules import BY_KEY, Level, level_for
from app.ingest.usgs import shaking_at

HORIZON = 60


@dataclass
class SiteImpact:
    site_key: str
    site_name: str
    country: str
    lat: float
    lon: float
    mmi: float | None
    pga_g: float | None
    level: Level
    outage_days: int
    suppliers: list[dict] = field(default_factory=list)  # {supplier_site_id, supplier_id, name}
    plants: list[str] = field(default_factory=list)


@dataclass
class Exposure:
    plant: str
    part_no: str
    category: str
    commodity: str
    level: Level
    impacted_share_pct: int
    single_source: bool
    on_hand: int
    daily_use: float
    cover_days: float
    stockout_day: int | None
    baseline_stockout_day: int | None
    at_risk_po_qty: int
    models: list[str]
    orders_at_risk: list[dict]
    sources: list[dict]
    arrivals: dict[int, int] = field(default_factory=dict)  # 第 t 天到貨量（已含地震影響），給補救方案求解器當起點

    @property
    def quake_caused(self) -> bool:
        return self.stockout_day is not None and (self.baseline_stockout_day is None or self.stockout_day < self.baseline_stockout_day)


@dataclass
class Assessment:
    scenario: dict
    sites: list[SiteImpact]
    exposures: list[Exposure]


def _rows(db: Session, sql: str) -> list[dict]:
    return [dict(r) for r in db.execute(text(sql)).mappings()]


def site_impacts(db: Session, event_id: str) -> dict[str, SiteImpact]:
    out: dict[str, SiteImpact] = {}
    used = _rows(db, """
        SELECT s.key, s.name, s.country, s.lat, s.lon, ss.id AS supplier_site_id, sp.id AS supplier_id, sp.name AS supplier_name,
               NULL AS plant
        FROM sites s JOIN supplier_sites ss ON ss.site_key = s.key JOIN suppliers sp ON sp.id = ss.supplier_id
        UNION ALL
        SELECT s.key, s.name, s.country, s.lat, s.lon, NULL, NULL, NULL, p.key FROM sites s JOIN plants p ON p.site_key = s.key""")
    for r in used:
        if r["key"] not in out:
            sh = shaking_at(event_id, r["lat"], r["lon"])
            lv = level_for(sh.mmi if sh else None)
            out[r["key"]] = SiteImpact(r["key"], r["name"], r["country"], r["lat"], r["lon"], sh.mmi if sh else None,
                                       sh.pga_g if sh else None, lv, lv.planning_outage_days)
        if r["plant"]:
            out[r["key"]].plants.append(r["plant"])
        else:
            out[r["key"]].suppliers.append({"supplier_site_id": r["supplier_site_id"], "supplier_id": r["supplier_id"],
                                            "name": r["supplier_name"]})
    return out


def _project(on_hand: int, daily: float, arrivals: dict[int, int], horizon: int) -> int | None:
    stock = float(on_hand)
    for t in range(1, horizon + 1):
        stock += arrivals.get(t, 0) - daily
        if stock < 0:
            return t
    return None


def assess(db: Session, scenario_key: str, horizon: int = HORIZON, outage_overrides: dict[str, int] | None = None) -> Assessment:
    sc = scenarios.get(scenario_key)
    sites = site_impacts(db, sc["event_id"])
    overrides = outage_overrides or {}
    site_of_ss = {s["supplier_site_id"]: s_key for s_key, si in sites.items() for s in si.suppliers}

    weekly = defaultdict(float)
    models_of = defaultdict(set)
    for r in _rows(db, "SELECT pp.plant, b.part_no, b.model, b.qty * pp.weekly_demand AS w FROM plant_products pp "
                       "JOIN bom b ON b.model = pp.model"):
        weekly[(r["plant"], r["part_no"])] += r["w"]
        models_of[(r["plant"], r["part_no"])].add(r["model"])
    part_weekly = defaultdict(float)
    for (_, p), w in weekly.items():
        part_weekly[p] += w
    sources = defaultdict(list)
    for r in _rows(db, "SELECT so.id, so.part_no, so.supplier_site_id, so.share_pct, so.weekly_capacity, so.price_usd::float AS price_usd, "
                       "sp.name AS supplier, sp.id AS supplier_id "
                       "FROM sourcing so JOIN supplier_sites ss ON ss.id = so.supplier_site_id JOIN suppliers sp ON sp.id = ss.supplier_id "
                       "WHERE so.qualified"):
        sources[r["part_no"]].append(r)
    pos = defaultdict(list)
    for r in _rows(db, "SELECT plant, sourcing_id, qty, due_day, transit_days, shipped FROM purchase_orders"):
        pos[(r["plant"], r["sourcing_id"])].append(r)
    last_due = {(r["plant"], r["sourcing_id"]): (r["last"], r["transit"]) for r in _rows(
        db, "SELECT plant, sourcing_id, MAX(due_day) AS last, MAX(transit_days) AS transit FROM purchase_orders GROUP BY plant, sourcing_id")}
    on_hand = {(r["plant"], r["part_no"]): r["on_hand"] for r in _rows(db, "SELECT plant, part_no, on_hand FROM inventory")}
    parts = {r["part_no"]: r for r in _rows(db, "SELECT part_no, category, commodity FROM parts")}
    orders = _rows(db, "SELECT id, plant, model, customer, qty, due_day FROM customer_orders")

    exposures = []
    for (plant, pn), w in weekly.items():
        srcs = sources[pn]
        levels = [sites[site_of_ss[s["supplier_site_id"]]].level for s in srcs]
        top = max(levels, key=lambda lv: lv.rank)
        if top.rank == 0:
            continue
        daily = w / 7

        def arrivals(with_quake: bool) -> tuple[dict[int, int], int]:
            arr: dict[int, int] = defaultdict(int)
            at_risk = 0
            for s in srcs:
                planned = sites[site_of_ss[s["supplier_site_id"]]].outage_days
                outage = overrides.get(s["supplier_site_id"], planned) if with_quake else 0
                last, transit = last_due.get((plant, s["id"]), (0, 7))
                lots = [(po["due_day"], po["qty"], po["transit_days"], po["shipped"]) for po in pos[(plant, s["id"])]]
                if s["share_pct"] > 0:
                    lots += [(day, round(w * s["share_pct"] / 100), transit, False) for day in range(last + 7, horizon + 1, 7)]
                per_day = s["weekly_capacity"] * w / part_weekly[pn] / 7
                cursor = float(outage)
                for due, qty, tr, shipped in sorted(lots):
                    day = max(due, 1)
                    if outage > 0 and not shipped:
                        start = max(float(due - tr), cursor)
                        cursor = start + qty / per_day
                        day = max(day, math.ceil(cursor) + tr)
                        if day > due:
                            at_risk += qty
                    if day <= horizon:
                        arr[day] += qty
            return arr, at_risk

        arr, at_risk = arrivals(True)
        base, _ = arrivals(False)
        oh = on_hand.get((plant, pn), 0)
        stockout = _project(oh, daily, arr, horizon)
        models = sorted(models_of[(plant, pn)])
        exposures.append(Exposure(
            plant=plant, part_no=pn, category=parts[pn]["category"], commodity=parts[pn]["commodity"], level=top,
            impacted_share_pct=sum(s["share_pct"] for s, lv in zip(srcs, levels) if lv.rank > 0),
            single_source=len(srcs) == 1, on_hand=oh, daily_use=round(daily, 2), cover_days=round(oh / daily, 1),
            stockout_day=stockout, baseline_stockout_day=_project(oh, daily, base, horizon), at_risk_po_qty=at_risk, models=models,
            orders_at_risk=[o for o in orders if stockout is not None and o["plant"] == plant and o["model"] in models
                            and o["due_day"] >= stockout],
            sources=[{**s, "site_key": site_of_ss[s["supplier_site_id"]], "level": lv.key,
                      "outage_days": overrides.get(s["supplier_site_id"], sites[site_of_ss[s["supplier_site_id"]]].outage_days)}
                     for s, lv in zip(srcs, levels)],
            arrivals=dict(arr)))
    exposures.sort(key=lambda e: (e.stockout_day is None, e.stockout_day or 0, -e.level.rank, e.cover_days))
    return Assessment(sc, sorted(sites.values(), key=lambda s: (-s.level.rank, -(s.mmi or 0))), exposures)


def level(key: str) -> Level:
    return BY_KEY[key]
