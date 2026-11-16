"""評測的標準答案：依 exposure.py 開頭的規格，用 pandas 與 scipy 另外實作一次。

刻意不引用被測模組（usgs.shaking_at、rules、exposure）：震度用 scipy 的網格內插直接讀 grid.npz，
等級門檻在這裡重新寫一次。兩邊若算出不同結果，代表其中一邊錯了，不會出現「拿被測程式驗證自己」。
"""

import math
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator
from sqlalchemy import create_engine

from app.config import settings

# (最低 MMI, 等級, 規劃停工天數)；由高到低
THRESHOLDS = [(8.0, "severe_damage", 90), (7.0, "damage_likely", 42), (6.0, "disruption_possible", 5), (5.0, "check", 0)]
RANK = {"none": 0, "check": 1, "disruption_possible": 2, "damage_likely": 3, "severe_damage": 4}


@lru_cache(maxsize=1)
def tables() -> dict[str, pd.DataFrame]:
    eng = create_engine(settings.database_url)
    names = ["sites", "plants", "supplier_sites", "sourcing", "bom", "plant_products", "inventory", "purchase_orders", "customer_orders"]
    return {n: pd.read_sql(f"SELECT * FROM {n}", eng) for n in names}


def mmi_at(event_id: str, lat: float, lon: float) -> float | None:
    with np.load(settings.data_dir / "real" / "usgs" / event_id / "grid.npz") as z:
        f = RegularGridInterpolator((z["lats"], z["lons"]), z["mmi"], bounds_error=False, fill_value=np.nan)
        v = float(f([[lat, lon]])[0])
    return None if math.isnan(v) else v


def classify(mmi: float | None) -> tuple[str, int]:
    for lo, key, days in THRESHOLDS:
        if mmi is not None and mmi >= lo:
            return key, days
    return "none", 0


def site_levels(event_id: str) -> pd.DataFrame:
    t = tables()
    used = set(t["supplier_sites"].site_key) | set(t["plants"].site_key)
    s = t["sites"][t["sites"].key.isin(used)].copy()
    s["mmi"] = [mmi_at(event_id, a, b) for a, b in zip(s.lat, s.lon)]
    s[["level", "outage"]] = [classify(m) for m in s.mmi]
    return s.set_index("key")


def expected(event_id: str, horizon: int = 60) -> dict[tuple[str, str], dict]:
    t = tables()
    lv = site_levels(event_id)
    src = t["sourcing"][t["sourcing"].qualified].merge(t["supplier_sites"][["id", "site_key"]], left_on="supplier_site_id", right_on="id",
                                                       suffixes=("", "_ss"))
    src["level"] = src.site_key.map(lv.level)
    src["outage"] = src.site_key.map(lv.outage)
    use = t["plant_products"].merge(t["bom"], on="model")
    use["w"] = use.qty * use.weekly_demand
    weekly = use.groupby(["plant", "part_no"]).w.sum()
    part_total = weekly.groupby(level="part_no").sum()
    models = use.groupby(["plant", "part_no"]).model.apply(set)
    inv = t["inventory"].set_index(["plant", "part_no"]).on_hand
    po = t["purchase_orders"]
    orders = t["customer_orders"]

    out = {}
    for (plant, pn), w in weekly.items():
        s = src[src.part_no == pn]
        if s.level.map(RANK).max() == 0:
            continue
        daily = w / 7

        def supply(quake: bool) -> tuple[np.ndarray, int]:
            arr = np.zeros(horizon + 1)
            delayed = 0
            for _, r in s.iterrows():
                outage = int(r.outage) if quake else 0
                mine = po[(po.plant == plant) & (po.sourcing_id == r.id)]
                last = int(mine.due_day.max()) if len(mine) else 0
                tr = int(mine.transit_days.max()) if len(mine) else 7
                lots = list(zip(mine.due_day, mine.qty, mine.transit_days, mine.shipped))
                if r.share_pct > 0:
                    lots += [(d, round(w * r.share_pct / 100), tr, False) for d in range(last + 7, horizon + 1, 7)]
                rate = r.weekly_capacity * w / part_total[pn] / 7
                free = float(outage)
                for due, qty, transit, shipped in sorted(lots):
                    arrive = max(int(due), 1)
                    if outage and not shipped:
                        free = max(float(due - transit), free) + qty / rate
                        arrive = max(arrive, math.ceil(free) + int(transit))
                        delayed += qty if arrive > due else 0
                    if arrive <= horizon:
                        arr[arrive] += qty
            return arr, delayed

        def first_short(arr: np.ndarray) -> int | None:
            stock = inv.get((plant, pn), 0) + np.cumsum(arr[1:]) - daily * np.arange(1, horizon + 1)
            neg = np.nonzero(stock < 0)[0]
            return int(neg[0]) + 1 if len(neg) else None

        arr, delayed = supply(True)
        stockout = first_short(arr)
        ms = models[(plant, pn)]
        hit = orders[(orders.plant == plant) & orders.model.isin(ms) & (orders.due_day >= (stockout or 10**9))]
        out[(plant, pn)] = {
            "level": max(s.level, key=RANK.get), "impacted_share_pct": int(s[s.level != "none"].share_pct.sum()),
            "stockout_day": stockout, "baseline_stockout_day": first_short(supply(False)[0]), "at_risk_po_qty": int(delayed),
            "orders_at_risk": sorted(hit.id.tolist()),
        }
    return out
