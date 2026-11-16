"""把各料件的最佳解組合成三個可比較的方案。"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.impact.exposure import Assessment
from app.plan import assumptions as A
from app.plan.solver import HORIZON, PROFILES, Problem, build, solve


def gap_reason(pb: Problem) -> str:
    """缺口補不上的原因（給比較說明用）。"""
    if not pb.sources and not pb.alternates:
        return "沒有其他合格來源，也沒有備援來源"
    if not pb.sources:
        fastest = min((A.QUALIFICATION_DAYS + a.lead_days for a in pb.alternates), default=None)
        return (f"其他合格來源都在停工；備援來源認證加交期最快要 {fastest} 天，超過規劃期 {HORIZON} 天"
                if fastest and fastest > HORIZON else "其他合格來源都在停工，備援來源產能不足")
    return "未停工來源的剩餘產能不足以補齊"


def options(db: Session, a: Assessment) -> dict:
    parts = sorted({e.part_no for e in a.exposures if e.quake_caused})
    problems = {pn: build(db, a, pn) for pn in parts}
    models_of = {}
    for r in db.execute(text("SELECT pp.plant, b.part_no, b.model FROM bom b JOIN plant_products pp ON pp.model = b.model")):
        models_of.setdefault((r[0], r[1]), set()).add(r[2])
    orders = [dict(r) for r in db.execute(text("SELECT id, plant, model, qty, due_day FROM customer_orders")).mappings()]

    def orders_hit(first_short: dict[tuple, int]) -> list[int]:
        hit = set()
        for (plant, pn), day in first_short.items():
            hit |= {o["id"] for o in orders if o["plant"] == plant and o["model"] in models_of[(plant, pn)] and o["due_day"] >= day}
        return sorted(hit)

    out = {"horizon_days": HORIZON, "parts": parts, "options": []}
    no_action = {(e.plant, e.part_no): e.stockout_day for e in a.exposures if e.quake_caused}
    out["no_action"] = {"orders_at_risk": len(orders_hit(no_action)), "stockouts": len(no_action)}
    for key, cfg in PROFILES.items():
        plans = [solve(problems[pn], key) for pn in parts]
        first = {(plant, p.part_no): d for p in plans for plant, d in p.first_short_day.items() if d}
        out["options"].append({
            "key": key, "label": cfg["label"], "cost_usd": round(sum(p.cost_usd for p in plans), 2),
            "shortage_units": sum(sum(p.shortage_units.values()) for p in plans),
            "loss_usd": round(sum(p.loss_usd for p in plans), 2),
            "orders_at_risk": len(orders_hit(first)), "parts_short": sorted({pn for _, pn in first}),
            "status": "optimal" if all(p.status == "optimal" for p in plans) else "check",
            "gap_reasons": {p.part_no: gap_reason(problems[p.part_no]) for p in plans if sum(p.shortage_units.values())},
            "plans": [vars(p) for p in plans],
        })
    return out
