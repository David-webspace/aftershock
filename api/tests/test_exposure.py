"""曝險計算對照獨立的標準答案（pandas＋scipy 另行實作），六起真實地震逐筆比對。"""

import pytest

from app.db import SessionLocal
from app.evals import oracle
from app.impact.exposure import assess
from app.impact.rules import level_for
from app.scenarios import all_scenarios


@pytest.mark.parametrize("key", list(all_scenarios()))
def test_matches_oracle(key):
    with SessionLocal() as db:
        got = {(e.plant, e.part_no): e for e in assess(db, key).exposures}
    want = oracle.expected(all_scenarios()[key]["event_id"])
    assert set(got) == set(want)
    for k, w in want.items():
        e = got[k]
        assert (e.level.key, e.impacted_share_pct, e.stockout_day, e.baseline_stockout_day, e.at_risk_po_qty) == (
            w["level"], w["impacted_share_pct"], w["stockout_day"], w["baseline_stockout_day"], w["at_risk_po_qty"]), k
        assert sorted(o["id"] for o in e.orders_at_risk) == w["orders_at_risk"], k


def test_site_levels_match_oracle():
    with SessionLocal() as db:
        sites = {s.site_key: s for s in assess(db, "tohoku-2011").sites}
    ref = oracle.site_levels("official20110311054624120_30")
    for key, row in ref.iterrows():
        assert sites[key].level.key == row.level, key
        if row.mmi is not None and sites[key].mmi is not None:
            assert abs(sites[key].mmi - row.mmi) < 0.02, key


def test_level_boundaries():
    assert [level_for(m).key for m in (None, 4.99, 5.0, 6.0, 7.0, 8.0)] == [
        "none", "none", "check", "disruption_possible", "damage_likely", "severe_damage"]


def test_controls_do_not_cause_stockouts():
    with SessionLocal() as db:
        for key in ("tainan-2025", "hualien-2024-08", "noto-2024-11", "myanmar-2025"):
            assert not [e for e in assess(db, key).exposures if e.quake_caused], key
        assert [e for e in assess(db, "tohoku-2011").exposures if e.quake_caused]


def test_no_baseline_shortage_in_synthetic_data():
    # 沒有地震時不應缺料，否則斷料無法歸因到地震
    with SessionLocal() as db:
        assert all(e.baseline_stockout_day is None for e in assess(db, "tohoku-2011").exposures)
