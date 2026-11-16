"""補救方案：對每個「地震造成斷料」的料件建一個混合整數規劃（OR-Tools／SCIP），由程式決定怎麼補，不交給模型。

規劃期 63 天；補救動作每週決定一次（第 1、8、15…天下單或調出），庫存逐日檢查，與曝險計算的斷料日一致。
對料件 p、使用它的每座工廠 k、第 d 天：

  庫存[k,d] ＝ 庫存[k,d-1] ＋ 原本會到的貨（已含地震延誤）＋ 追加訂單 ＋ 備援來源 ＋ 調入 － 調出 － 日用量 ＋ 缺料

手段：
- 追加訂單：向未停工的合格來源，用其剩餘週產能（週產能 － 平常分給這個料件的量）。下單後約 7 天出貨，
  海運（或同國陸運）照原運輸天數、空運 3 天。成本＝與受影響來源的單價差（不低於 0）＋處理成本 2%＋空運加價。
- 調撥：工廠間互調庫存，4 天到；調出的工廠調撥後至少保留 7 天用量。成本＝單價的 5%。
- 備援來源：尚未認證的來源，認證 21 天＋其交期後才能到貨；啟用有一次性成本。
- 缺料：未滿足的用量，每個料件的損失＝（用到它的成品單價 × 毛利率 ÷ 每台用量）中的最大值。

三種方案：
- 最低成本：只用海運追加與調撥（不空運、不啟用備援來源），缺料照毛利計損失
- 平衡：所有手段，缺料照毛利計損失
- 最少缺料：所有手段，缺料損失乘以 50 倍（願意多花錢換取不缺料）
"""

import math
from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.impact.exposure import Assessment
from app.plan import assumptions as A

WEEKS = 9
HORIZON = WEEKS * 7
TIE_BREAK = 1e-6


@dataclass
class PlantData:
    plant: str
    country: str
    on_hand: int
    daily: float
    base: list[int]  # 第 1..HORIZON 天原本會到的量（index＝天數－1）
    penalty: float


@dataclass
class SourceData:
    sourcing_id: int
    supplier_id: str
    supplier: str
    site_key: str
    country: str
    price: float
    spare_weekly: int
    sea_transit: dict[str, int]  # plant → 天數


@dataclass
class AltData:
    sourcing_id: int
    supplier_id: str
    supplier: str
    price: float
    weekly_capacity: int
    lead_days: int


@dataclass
class Problem:
    part_no: str
    category: str
    affected_price: float
    plants: list[PlantData]
    sources: list[SourceData]
    alternates: list[AltData]


@dataclass
class PartPlan:
    part_no: str
    category: str
    actions: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    shortage_units: dict[str, int] = field(default_factory=dict)
    first_short_day: dict[str, int | None] = field(default_factory=dict)
    loss_usd: float = 0.0
    status: str = "optimal"
    objective: float = 0.0


PROFILES = {
    "low_cost": {"label": "最低成本", "extra": True, "transfer": True, "air": False, "alternates": False, "mult": 1},
    "balanced": {"label": "平衡", "extra": True, "transfer": True, "air": True, "alternates": True, "mult": 1},
    "min_shortage": {"label": "最少缺料", "extra": True, "transfer": True, "air": True, "alternates": True,
                     "mult": A.MIN_SHORTAGE_PENALTY_MULTIPLIER},
}
NO_ACTION = {"label": "不採取行動", "extra": False, "transfer": False, "air": False, "alternates": False, "mult": 1}


def build(db: Session, a: Assessment, part_no: str) -> Problem:
    exps = [e for e in a.exposures if e.part_no == part_no]
    country = {r[0]: r[1] for r in db.execute(text("SELECT p.key, s.country FROM plants p JOIN sites s ON s.key = p.site_key"))}
    values = {}
    for r in db.execute(text("SELECT pp.plant, b.model, b.qty FROM bom b JOIN plant_products pp ON pp.model = b.model WHERE b.part_no = :p"),
                        {"p": part_no}):
        values[r[0]] = max(values.get(r[0], 0), A.PRODUCT_VALUE_USD[r[1]] * A.MARGIN / r[2])
    plants = []
    for e in exps:
        base = [0] * HORIZON
        for day, qty in e.arrivals.items():
            if 1 <= day <= HORIZON:
                base[day - 1] += qty
        plants.append(PlantData(e.plant, country[e.plant], e.on_hand, e.daily_use, base, values[e.plant]))
    srcs = exps[0].sources
    total_weekly = sum(p.daily for p in plants) * 7
    affected = [s for s in srcs if s["outage_days"] > 0]
    affected_price = max((s["price_usd"] for s in affected), default=0.0)
    site_country = {r[0]: r[1] for r in db.execute(text("SELECT key, country FROM sites"))}
    transit = {(r[0], r[1]): r[2] for r in db.execute(text(
        "SELECT plant, sourcing_id, MAX(transit_days) FROM purchase_orders po JOIN sourcing so ON so.id = po.sourcing_id "
        "WHERE so.part_no = :p GROUP BY plant, sourcing_id"), {"p": part_no})}
    sources = []
    for s in srcs:
        if s["outage_days"] > 0:
            continue
        spare = int(s["weekly_capacity"] - total_weekly * s["share_pct"] / 100)
        if spare <= 0:
            continue
        sources.append(SourceData(s["id"], s["supplier_id"], s["supplier"], s["site_key"], site_country[s["site_key"]], s["price_usd"], spare,
                                  {p.plant: transit.get((p.plant, s["id"]), 2 if site_country[s["site_key"]] == p.country else 12)
                                   for p in plants}))
    alts = [AltData(r["id"], r["supplier_id"], r["name"], float(r["price_usd"]), r["weekly_capacity"], r["lead_days"]) for r in db.execute(text(
        "SELECT so.id, sp.id AS supplier_id, sp.name, so.price_usd, so.weekly_capacity, so.lead_days FROM sourcing so "
        "JOIN supplier_sites ss ON ss.id = so.supplier_site_id JOIN suppliers sp ON sp.id = ss.supplier_id "
        "WHERE so.part_no = :p AND NOT so.qualified"), {"p": part_no}).mappings()]
    return Problem(part_no, exps[0].category, affected_price, plants, sources, alts)


def solve(pb: Problem, profile: str) -> PartPlan:
    cfg = PROFILES.get(profile, NO_ACTION)

    def unit_cost(src: SourceData, mode: str) -> float:
        air = max(A.AIR_PREMIUM_MIN_USD, src.price * A.AIR_PREMIUM_RATE) if mode == "air" else 0
        return max(0.0, src.price - pb.affected_price) + src.price * A.EXTRA_HANDLING_RATE + air

    s = pywraplp.Solver.CreateSolver("SCIP")
    D, P = range(1, HORIZON + 1), pb.plants
    inv = {(p.plant, d): s.NumVar(0, s.infinity(), f"I_{p.plant}_{d}") for p in P for d in D}
    short = {(p.plant, d): s.NumVar(0, s.infinity(), f"S_{p.plant}_{d}") for p in P for d in D}
    cost_terms = []
    # 每個決策：(變數, 到貨工廠, 到貨日, 說明)；調撥另記出貨工廠與出貨日
    arrivals: list[tuple] = []
    shipments: list[tuple] = []
    meta: list[dict] = []
    order_days = [(w - 1) * 7 + 1 for w in range(1, WEEKS + 1)]  # 每週下一次單

    if cfg["extra"]:
        for src in pb.sources:
            per_week = {od: [] for od in order_days}
            for p in P:
                modes = {"truck" if src.country == p.country else "sea": src.sea_transit[p.plant]}
                if cfg["air"] and src.country != p.country:
                    modes["air"] = A.AIR_TRANSIT_DAYS
                for mode, transit in modes.items():
                    for od in order_days:
                        arrive = od + A.EXTRA_ORDER_PREP_DAYS + transit
                        if arrive > HORIZON:
                            continue
                        v = s.IntVar(0, src.spare_weekly, f"x_{src.sourcing_id}_{p.plant}_{mode}_{od}")
                        # 同樣成本時偏好早點下單（較保險）；權重極小，不影響方案取捨
                        cost_terms.append((unit_cost(src, mode) + TIE_BREAK * od) * v)
                        arrivals.append((v, p.plant, arrive))
                        meta.append({"var": v, "type": "extra_order", "key": ("extra", src.sourcing_id, p.plant, mode), "src": src,
                                     "plant": p.plant, "mode": mode, "order_day": od, "arrive_day": arrive, "unit": unit_cost(src, mode)})
                        per_week[od].append(v)
            for vs in per_week.values():
                if vs:
                    s.Add(sum(vs) <= src.spare_weekly)  # 剩餘產能以下單的那一週計

    if cfg["transfer"]:
        for i in P:
            keep = i.daily * A.TRANSFER_KEEP_DAYS
            for od in order_days:
                if od + A.TRANSFER_DAYS > HORIZON:
                    continue
                outs = []
                for j in P:
                    if i.plant == j.plant:
                        continue
                    v = s.IntVar(0, i.on_hand + sum(i.base), f"t_{i.plant}_{j.plant}_{od}")
                    unit = A.TRANSFER_RATE * max(pb.affected_price, 0.01)
                    cost_terms.append(unit * v)
                    arrivals.append((v, j.plant, od + A.TRANSFER_DAYS))
                    shipments.append((v, i.plant, od))
                    meta.append({"var": v, "type": "transfer", "key": ("transfer", i.plant, j.plant), "from": i.plant, "plant": j.plant,
                                 "order_day": od, "arrive_day": od + A.TRANSFER_DAYS, "unit": unit})
                    outs.append(v)
                b = s.BoolVar(f"b_{i.plant}_{od}")
                s.Add(sum(outs) <= (i.on_hand + sum(i.base)) * b)
                s.Add(inv[(i.plant, od)] >= keep * b)  # 調出當天之後仍保留 7 天用量

    ys = {}
    if cfg["alternates"]:
        for alt in pb.alternates:
            if A.QUALIFICATION_DAYS + alt.lead_days > HORIZON:
                continue
            y = s.BoolVar(f"y_{alt.sourcing_id}")
            ys[alt.sourcing_id] = (y, alt)
            cost_terms.append(A.QUALIFICATION_COST_USD * y)
            unit = max(0.0, alt.price - pb.affected_price) + alt.price * A.EXTRA_HANDLING_RATE
            for od in order_days:
                arrive = A.QUALIFICATION_DAYS + alt.lead_days + od - 1
                if arrive > HORIZON:
                    continue
                vs = []
                for p in P:
                    v = s.IntVar(0, alt.weekly_capacity, f"z_{alt.sourcing_id}_{p.plant}_{od}")
                    cost_terms.append(unit * v)
                    arrivals.append((v, p.plant, arrive))
                    meta.append({"var": v, "type": "qualify_alternate", "key": ("alt", alt.sourcing_id), "alt": alt, "plant": p.plant,
                                 "order_day": od, "arrive_day": arrive, "unit": unit})
                    vs.append(v)
                s.Add(sum(vs) <= alt.weekly_capacity * y)

    arr_at = {}
    for v, k, d in arrivals:
        arr_at.setdefault((k, d), []).append(v)
    ship_at = {}
    for v, k, d in shipments:
        ship_at.setdefault((k, d), []).append(v)
    for p in P:
        for d in D:
            prev = p.on_hand if d == 1 else inv[(p.plant, d - 1)]
            s.Add(inv[(p.plant, d)] == prev + p.base[d - 1] + sum(arr_at.get((p.plant, d), [])) - sum(ship_at.get((p.plant, d), []))
                  - p.daily + short[(p.plant, d)])
            # 越早缺料越嚴重（多 1% 以內）：同樣的缺料量，求解器會先用完庫存，第一個缺料日與曝險計算一致
            cost_terms.append(p.penalty * cfg["mult"] * (1 + 0.01 * (HORIZON - d) / HORIZON) * short[(p.plant, d)])

    s.Minimize(sum(cost_terms))
    s.SetTimeLimit(30_000)
    params = pywraplp.MPSolverParameters()
    # 預設相對差距約 1e-4，比「早一天缺料」的權重差還大，會停在提早缺料的次佳解
    params.SetDoubleParam(pywraplp.MPSolverParameters.RELATIVE_MIP_GAP, 1e-9)
    status = s.Solve(params)
    plan = PartPlan(pb.part_no, pb.category)
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        plan.status = "infeasible"
        return plan
    plan.status = "optimal" if status == pywraplp.Solver.OPTIMAL else "feasible"
    plan.objective = s.Objective().Value()

    agg: dict[tuple, dict] = {}
    for m in meta:
        q = round(m["var"].solution_value())
        if not q:
            continue
        if m["type"] == "extra_order":
            a = agg.setdefault(m["key"], {"type": "extra_order", "sourcing_id": m["src"].sourcing_id, "supplier_id": m["src"].supplier_id,
                                          "supplier": m["src"].supplier, "plant": m["plant"], "mode": m["mode"], "qty": 0, "lots": [],
                                          "cost_usd": 0.0})
        elif m["type"] == "transfer":
            a = agg.setdefault(m["key"], {"type": "transfer", "from": m["from"], "plant": m["plant"], "qty": 0, "lots": [], "cost_usd": 0.0})
        else:
            alt = m["alt"]
            a = agg.setdefault(m["key"], {"type": "qualify_alternate", "sourcing_id": alt.sourcing_id, "supplier_id": alt.supplier_id,
                                          "supplier": alt.supplier, "qty": 0, "lots": [], "cost_usd": A.QUALIFICATION_COST_USD})
        a["qty"] += q
        a["lots"].append({"plant": m["plant"], "order_day": m["order_day"], "arrive_day": m["arrive_day"], "qty": q})
        a["cost_usd"] += q * m["unit"]
    plan.actions = [{**a, "cost_usd": round(a["cost_usd"], 2)} for a in agg.values()]
    plan.cost_usd = round(sum(a["cost_usd"] for a in plan.actions), 2)
    for p in P:
        units = [short[(p.plant, d)].solution_value() for d in D]
        plan.shortage_units[p.plant] = round(sum(u for u in units if u >= 0.5))
        # 半個單位以下視為求解器的數值誤差，不算缺料
        plan.first_short_day[p.plant] = next((d for d, u in zip(D, units) if u >= 0.5), None)
        plan.loss_usd += sum(units) * p.penalty
    plan.loss_usd = round(plan.loss_usd, 2)
    return plan
