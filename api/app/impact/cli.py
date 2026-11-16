"""python -m app.impact.cli hualien-2024    印出某起地震的受影響廠區與斷料風險。"""

import sys

from app.db import SessionLocal
from app.impact.exposure import assess
from app.scenarios import all_scenarios


def main(key: str) -> None:
    with SessionLocal() as db:
        a = assess(db, key)
    sc = a.scenario
    print(f"{sc['label']}  {sc['place']}  T0 {sc['t0']:%Y-%m-%d %H:%M}（台北）")
    print("\n受影響廠區")
    for s in a.sites:
        if s.level.rank == 0:
            continue
        who = "、".join([x["name"] for x in s.suppliers] + [f"自有工廠 {p}" for p in s.plants])
        print(f"  {s.level.label:<8} MMI {s.mmi:.1f}  PGA {s.pga_g:.2f} g  {s.site_name}：{who}")
    risky = [e for e in a.exposures if e.quake_caused]
    print(f"\n需確認的工廠×料件 {len(a.exposures)} 筆；地震造成斷料 {len(risky)} 筆")
    for e in risky:
        tag = "單一來源" if e.single_source else f"受影響來源占 {e.impacted_share_pct}%"
        print(f"  {e.plant} {e.part_no}（{e.category}）{tag}，庫存可撐 {e.cover_days} 天，預估第 {e.stockout_day} 天斷料，"
              f"影響客戶訂單 {len(e.orders_at_risk)} 張")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in all_scenarios():
        sys.exit(f"用法：python -m app.impact.cli <{'|'.join(all_scenarios())}>")
    main(sys.argv[1])
