"""補救方案：不行動時與曝險計算一致、方案可行（逐日重播驗證）、手段符合方案設定、小型問題對照暴力搜尋。"""

import itertools

import pytest

from app.db import SessionLocal
from app.impact.exposure import assess
from app.plan import assumptions as A
from app.plan.options import options
from app.plan.solver import HORIZON, PROFILES, TIE_BREAK, PlantData, Problem, SourceData, build, solve

SCENARIOS = ["hualien-2024", "tohoku-2011"]


@pytest.fixture(scope="module")
def solved():
    out = {}
    with SessionLocal() as db:
        for k in SCENARIOS:
            a = assess(db, k, horizon=HORIZON)
            parts = sorted({e.part_no for e in a.exposures if e.quake_caused})
            out[k] = (a, {pn: build(db, a, pn) for pn in parts})
    return out


def test_no_action_matches_exposure(solved):
    for a, problems in solved.values():
        for e in (e for e in a.exposures if e.quake_caused):
            assert solve(problems[e.part_no], "none").first_short_day[e.plant] == e.stockout_day


def _replay(pb: Problem, plan) -> dict[str, float]:
    """不靠求解器的變數，用方案的動作逐日重播庫存，回傳各廠缺料量，並檢查調出後仍保留 7 天用量。"""
    arrive, ship = {}, {}
    for act in plan.actions:
        for lot in act["lots"]:
            arrive[(lot["plant"], lot["arrive_day"])] = arrive.get((lot["plant"], lot["arrive_day"]), 0) + lot["qty"]
            if act["type"] == "transfer":
                ship[(act["from"], lot["order_day"])] = ship.get((act["from"], lot["order_day"]), 0) + lot["qty"]
    short = {}
    for p in pb.plants:
        stock, missing = float(p.on_hand), 0.0
        for d in range(1, HORIZON + 1):
            stock += p.base[d - 1] + arrive.get((p.plant, d), 0) - ship.get((p.plant, d), 0) - p.daily
            if ship.get((p.plant, d)):
                assert stock >= p.daily * A.TRANSFER_KEEP_DAYS - 1, (p.plant, d)
            if stock < 0:
                missing, stock = missing - stock, 0.0
        short[p.plant] = missing
    return short


@pytest.mark.parametrize("profile", list(PROFILES))
def test_plans_are_feasible_and_respect_profile(solved, profile):
    cfg = PROFILES[profile]
    for _, problems in solved.values():
        for pb in problems.values():
            plan = solve(pb, profile)
            assert plan.status == "optimal"
            replay = _replay(pb, plan)
            for plant, units in plan.shortage_units.items():
                assert abs(replay[plant] - units) <= 1, (pb.part_no, plant)
            spare = {s.sourcing_id: s.spare_weekly for s in pb.sources}
            used = {}
            for act in plan.actions:
                if act["type"] == "extra_order":
                    assert cfg["air"] or act["mode"] != "air"
                    for lot in act["lots"]:
                        used[(act["sourcing_id"], lot["order_day"])] = used.get((act["sourcing_id"], lot["order_day"]), 0) + lot["qty"]
                assert cfg["alternates"] or act["type"] != "qualify_alternate"
            assert all(q <= spare[sid] for (sid, _), q in used.items())


def test_more_levers_never_worse(solved):
    for _, problems in solved.values():
        for pb in problems.values():
            low, bal = solve(pb, "low_cost"), solve(pb, "balanced")
            assert bal.objective <= low.objective + 1e-6  # 平衡方案的手段是最低成本方案的超集合，同樣懲罰下不會更差
            assert sum(solve(pb, "min_shortage").shortage_units.values()) <= sum(bal.shortage_units.values()) + 1


def test_options_summary(solved):
    with SessionLocal() as db:
        o = options(db, solved["hualien-2024"][0])
    assert o["no_action"]["stockouts"] == 4 and o["no_action"]["orders_at_risk"] > 0
    assert all(op["orders_at_risk"] <= o["no_action"]["orders_at_risk"] for op in o["options"])


def test_matches_brute_force_on_small_problem():
    # 一座工廠、一個來源：每週最多追加 3 單位，逐一列舉 9 週的所有下單組合（4^9 種），找最小總成本
    plant = PlantData("K", "TW", on_hand=10, daily=1.0, base=[0] * HORIZON, penalty=5.0)
    src = SourceData(1, "S1", "test", "X", "JP", price=2.0, spare_weekly=3, sea_transit={"K": 10})
    pb = Problem("P", "test", affected_price=2.0, plants=[plant], sources=[src], alternates=[])
    plan = solve(pb, "low_cost")
    order_days = [(w - 1) * 7 + 1 for w in range(1, 10)]
    unit = src.price * A.EXTRA_HANDLING_RATE
    best = float("inf")
    for qs in itertools.product(range(4), repeat=9):
        arrive, cost = {}, 0.0
        for od, q in zip(order_days, qs):
            day = od + A.EXTRA_ORDER_PREP_DAYS + 10
            if q and day > HORIZON:
                break
            if q:
                arrive[day] = arrive.get(day, 0) + q
                cost += q * (unit + TIE_BREAK * od)
        else:
            stock = 10.0
            for d in range(1, HORIZON + 1):
                stock += arrive.get(d, 0) - 1.0
                if stock < 0:
                    cost += -stock * 5.0 * (1 + 0.01 * (HORIZON - d) / HORIZON)
                    stock = 0.0
            best = min(best, cost)
    assert abs(plan.objective - best) < 1e-4
