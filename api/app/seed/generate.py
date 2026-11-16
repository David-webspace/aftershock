"""合成採購資料（固定種子，可重現），放在真實工業區上。

- 工業區座標：data/real/sites.json（真實）
- 料件類別與規格：catalog.yaml（依 TI 公開參考設計校準）
- 供應商、聯絡人、料號、價格、交期、庫存、採購單、客戶訂單：合成。公司名稱以隨機音節組合產生，
  並排除知名電子業者名稱；若與真實公司雷同純屬巧合。Email 一律使用保留網域 .example。
- 日期一律為相對 T0（地震發生日）的天數。

python -m app.seed.generate
"""

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import delete, insert

from app.config import settings
from app.db import SessionLocal
from app.ingest.sites import load as load_sites
from app.models import (BomLine, Contact, CustomerOrder, Inventory, Part, Plant, PlantProduct, Product, PurchaseOrder, Site,
                        Sourcing, Supplier, SupplierSite)

SEED = 20240403
CATALOG = yaml.safe_load(Path(__file__).with_name("catalog.yaml").read_text())
SUPPLIERS_PER_COMMODITY = {"semiconductor": 14, "passive": 12, "magnetic": 10, "pcb": 6, "mechanical": 10, "electromechanical": 6}
SINGLE_SOURCE_P = {"semiconductor": 0.35, "passive": 0.15, "magnetic": 0.2, "pcb": 0.1, "mechanical": 0.15, "electromechanical": 0.25}
COVER_DAYS = {"semiconductor": (18, 55), "passive": (10, 35), "magnetic": (7, 21), "pcb": (5, 14), "mechanical": (5, 14),
              "electromechanical": (8, 25)}

# 知名電子、電源、被動元件業者（及其常見簡稱）：產生的名稱若包含這些字，重抽
FAMOUS = {"delta", "foxconn", "hon hai", "tsmc", "murata", "tdk", "yageo", "walsin", "nichicon", "rubycon",
          "infineon", "renesas", "rohm", "toshiba", "panasonic", "kemet", "vishay", "taiyo", "chemi-con", "kyocera", "omron",
          "texas", "onsemi", "nexperia", "diodes", "littelfuse", "bourns", "eaton", "molex", "amphenol", "te connect", "unimicron",
          "tripod", "compeq", "wus", "zhen ding", "sunon", "nidec", "avc", "auras", "chicony", "acbel", "salcomp", "flex", "jabil",
          "pegatron", "quanta", "wistron", "inventec", "lingyi", "luxshare", "goertek", "sunlord", "fenghua", "aihua", "jianghai",
          "ssm", "inpaq", "cyntec", "darfon", "chilisin", "shih her", "everlight", "kingbright", "ase", "spil", "powertech", "hana",
          "kce", "cal-comp", "fabrinet", "svi", "ionics", "integrated micro", "vitrox", "inari", "unisem", "globetronics", "mtron",
          "sumida", "tamura", "fdk", "koa", "susumu", "alps", "hirose", "jae", "yokowo", "shindengen", "sanken", "fuji", "mitsubishi"}

TW_SYL = ["Hsin", "Kai", "Lung", "Feng", "Tien", "Yao", "Chuan", "Wei", "Sheng", "Jun", "Pei", "Ming", "Ting", "Yu", "Chen", "Kuan"]
JP_A = ["Kuro", "Asa", "Mino", "Tsuru", "Hoshi", "Kawa", "Sena", "Yori", "Mizu", "Taki", "Shira", "Hagi", "Oto", "Nagi"]
JP_B = ["shima", "gawa", "tani", "mura", "zaki", "hara", "oka", "dera"]
CN_SYL = ["Xin", "Hua", "Rui", "Jia", "Yong", "Kang", "Tian", "Bo", "Ding", "Heng", "Lian", "Qi", "Shun", "Zhao", "Yue", "Cheng"]
INTL = ["Orvia", "Kelmar", "Veltra", "Norvex", "Calden", "Mirexa", "Trovan", "Sorell", "Pantrex", "Lumora", "Daxen", "Corvel",
        "Altrona", "Benvio", "Querra", "Zenvar", "Halvex", "Ostrel", "Pyrona", "Ravenna", "Tessaro", "Ulvian"]
SUFFIX = {"semiconductor": ["Semiconductor", "Microdevices", "Power Devices"], "passive": ["Components", "Capacitor", "Electronic Parts"],
          "magnetic": ["Magnetics", "Coil", "Transformer"], "pcb": ["Circuit", "PCB", "Interconnect"],
          "mechanical": ["Metal Works", "Precision Industry", "Thermal"], "electromechanical": ["Connector", "Electro-Mech", "Terminal"]}
JP_SUFFIX = {"semiconductor": "Denshi", "passive": "Denki", "magnetic": "Denki", "pcb": "Kiban", "mechanical": "Seiki",
             "electromechanical": "Tsushin"}
GIVEN = {"TW": ["Ivy Lin", "Kevin Chang", "Grace Hsu", "Jason Wu", "Mia Tsai", "Leo Huang"],
         "JP": ["Haruka Sato", "Kenji Watanabe", "Yui Tanaka", "Daisuke Ito", "Mai Kobayashi", "Shota Yamamoto"],
         "CN": ["Li Wen", "Zhang Hao", "Chen Jing", "Wang Lei", "Liu Yan", "Zhao Min"],
         "TH": ["Nattapong S.", "Siriporn K.", "Anan W."], "MY": ["Aisyah Rahman", "Daniel Tan", "Priya Nair"],
         "VN": ["Nguyen Thu Ha", "Tran Minh Duc", "Le Thi Mai"], "PH": ["Maria Santos", "Joel Reyes", "Angela Cruz"],
         "MX": ["Carlos Ramírez", "Lucía Hernández", "Diego Torres"], "ID": ["Budi Santoso", "Sari Wulandari"]}
TITLES = ["Sales Manager", "Account Manager", "Customer Service", "Plant Manager"]


def _name(rng: np.random.Generator, country: str, commodity: str, used: set[str]) -> str:
    while True:
        if country == "TW":
            base = "".join(rng.choice(TW_SYL, 2, replace=False)).capitalize()
            name = f"{base} {rng.choice(SUFFIX[commodity])}"
        elif country == "JP":
            name = f"{rng.choice(JP_A)}{rng.choice(JP_B)} {JP_SUFFIX[commodity]}"
        elif country == "CN":
            name = f"{''.join(rng.choice(CN_SYL, 2, replace=False)).capitalize()} {rng.choice(SUFFIX[commodity])}"
        else:
            name = f"{rng.choice(INTL)} {rng.choice(SUFFIX[commodity])} ({country})"
        low = name.lower()
        if name not in used and not any(f in low for f in FAMOUS):
            used.add(name)
            return name


def _pick_country(rng: np.random.Generator, weights: dict[str, int]) -> str:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return str(rng.choice(keys, p=p / p.sum()))


def generate() -> dict:
    rng = np.random.default_rng(SEED)
    sites = load_sites()
    by_country = defaultdict(list)
    for s in sites:
        by_country[s["country"]].append(s["key"])
    own_sites = {p["site"] for p in CATALOG["plants"]}

    # 料件
    parts, part_family = [], {}
    fam_by_key = {f["key"]: f for f in CATALOG["families"]}
    for f in CATALOG["families"]:
        for i, spec in enumerate(f["variants"]):
            pn = f"ARC-{f['key'].upper().replace('_', '')}-{i + 1:02d}"
            parts.append({"part_no": pn, "family": f["key"], "category": f["category"], "commodity": f["commodity"], "spec": spec})
            part_family[f"{f['key']}:{i}"] = pn

    # 供應商與廠區
    suppliers, supplier_sites, contacts, used = [], [], [], set()
    by_commodity = defaultdict(list)
    sid = 0
    for commodity, n in SUPPLIERS_PER_COMMODITY.items():
        for _ in range(n):
            sid += 1
            country = _pick_country(rng, CATALOG["sourcing_countries"][commodity])
            supplier = {"id": f"S{sid:03d}", "name": _name(rng, country, commodity, used), "country": country, "commodity": commodity,
                        "currency": CATALOG["currency"][country], "language": CATALOG["language"][country]}
            suppliers.append(supplier)
            candidates = [k for k in by_country[country] if k not in own_sites] or by_country[country]
            n_sites = int(rng.choice([1, 1, 2, 2, 3]))
            chosen = list(rng.choice(candidates, min(n_sites, len(candidates)), replace=False))
            # 一部分供應商另有一座海外廠（台、日業者常見的分散布局）
            if country in ("TW", "JP") and rng.random() < 0.35:
                other = str(rng.choice(["CN", "TH", "MY", "VN", "PH"]))
                chosen.append(str(rng.choice(by_country[other])))
            for j, key in enumerate(chosen, 1):
                supplier_sites.append({"id": f"{supplier['id']}-{j}", "supplier_id": supplier["id"], "site_key": key})
            domain = supplier["name"].split(" ")[0].lower() + ".example"
            for k in range(int(rng.integers(1, 3))):
                person = str(rng.choice(GIVEN[country]))
                local = re.sub(r"[^a-z]+", ".", unicodedata.normalize("NFKD", person).encode("ascii", "ignore").decode().lower()).strip(".")
                contacts.append({"supplier_id": supplier["id"], "name": person, "email": f"{local}@{domain}", "title": TITLES[k]})
            by_commodity[commodity].append(supplier)
    sites_of = defaultdict(list)
    for ss in supplier_sites:
        sites_of[ss["supplier_id"]].append(ss["id"])

    # 成品、BOM、各廠需求
    products = [{"model": p["model"], "name": p["name"]} for p in CATALOG["products"]]
    bom = [{"model": p["model"], "part_no": part_family[k], "qty": q} for p in CATALOG["products"] for k, q in p["bom"].items()]
    plants = [{"key": p["key"], "site_key": p["site"], "name": p["name"]} for p in CATALOG["plants"]]
    demand_range = {p["model"]: p["weekly_demand"] for p in CATALOG["products"]}
    makers = defaultdict(list)
    for p in CATALOG["plants"]:
        for m in p["products"]:
            makers[m].append(p["key"])
    plant_products = []
    for model, plant_keys in makers.items():
        total = int(rng.integers(*demand_range[model]))
        share = rng.dirichlet(np.ones(len(plant_keys)) * 3)
        plant_products += [{"plant": k, "model": model, "weekly_demand": max(100, int(total * s / 10) * 10)} for k, s in zip(plant_keys, share)]

    weekly_use = defaultdict(float)  # (plant, part) → 每週用量
    for pp in plant_products:
        for b in bom:
            if b["model"] == pp["model"]:
                weekly_use[(pp["plant"], b["part_no"])] += b["qty"] * pp["weekly_demand"]
    part_total = defaultdict(float)
    for (_, pn), q in weekly_use.items():
        part_total[pn] += q

    # 合格來源
    sourcing, sid = [], 0
    for part in parts:
        if part_total[part["part_no"]] == 0:
            continue
        f = fam_by_key[part["family"]]
        pool = by_commodity[part["commodity"]]
        n_src = 1 if rng.random() < SINGLE_SOURCE_P[part["commodity"]] else int(rng.choice([2, 2, 3]))
        chosen = list(rng.choice(len(pool), min(n_src, len(pool)), replace=False))
        shares = np.round(rng.dirichlet(np.ones(len(chosen)) * 2) * 100).astype(int)
        shares[0] += 100 - shares.sum()
        base_price = rng.uniform(*f["unit_usd"])
        for idx, share in zip(chosen, shares):
            sup = pool[idx]
            sid += 1
            sourcing.append({
                "id": sid, "part_no": part["part_no"], "supplier_site_id": str(rng.choice(sites_of[sup["id"]])), "qualified": True,
                "share_pct": int(share), "lead_days": int(rng.integers(*f["lead_weeks"]) * 7), "moq": _moq(rng, base_price),
                "price_usd": round(base_price * rng.uniform(0.92, 1.1), 5),
                "weekly_capacity": int(part_total[part["part_no"]] * rng.uniform(0.9, 2.2)),
            })
        # 單一來源料件中，約一半另有一家尚未完成認證的備援來源（補救方案可考慮加速認證）
        if n_src == 1 and rng.random() < 0.5:
            alt = pool[int(rng.integers(len(pool)))]
            if alt["id"] != pool[chosen[0]]["id"]:
                sid += 1
                sourcing.append({
                    "id": sid, "part_no": part["part_no"], "supplier_site_id": str(rng.choice(sites_of[alt["id"]])), "qualified": False,
                    "share_pct": 0, "lead_days": int(rng.integers(*f["lead_weeks"]) * 7 + 14), "moq": _moq(rng, base_price),
                    "price_usd": round(base_price * rng.uniform(1.05, 1.3), 5),
                    "weekly_capacity": int(part_total[part["part_no"]] * rng.uniform(0.4, 1.0)),
                })

    # 庫存（依類別給不同的安全天數）與未結採購單
    site_country = {s["key"]: s["country"] for s in sites}
    ss_country = {ss["id"]: site_country[ss["site_key"]] for ss in supplier_sites}
    plant_country = {p["key"]: site_country[p["site"]] for p in CATALOG["plants"]}
    commodity_of = {p["part_no"]: p["commodity"] for p in parts}
    inventory, pos, po_seq = [], [], 0
    for (plant, pn), weekly in weekly_use.items():
        daily = weekly / 7
        inventory.append({"plant": plant, "part_no": pn, "on_hand": int(daily * rng.uniform(*COVER_DAYS[commodity_of[pn]]))})
        for src in (s for s in sourcing if s["part_no"] == pn and s["qualified"]):
            same_country = ss_country[src["supplier_site_id"]] == plant_country[plant]
            mode = "truck" if same_country else ("air" if rng.random() < 0.12 else "sea")
            transit = {"truck": 2, "sea": int(rng.integers(8, 15)), "air": 3}[mode]
            weekly_qty = max(src["moq"], int(weekly * src["share_pct"] / 100))
            # 每週一張，交期涵蓋 T0 前一週（已出貨在途）到一個完整交期之後
            for due in range(int(rng.integers(-6, 1)), src["lead_days"] + 1, 7):
                po_seq += 1
                pos.append({"po_no": f"PO{po_seq:06d}", "plant": plant, "sourcing_id": src["id"],
                            "qty": int(weekly_qty * rng.uniform(0.85, 1.15)), "order_day": due - src["lead_days"], "due_day": due,
                            "mode": mode, "transit_days": transit, "shipped": due - transit <= 0})

    # 客戶訂單（未來 8 週）
    customers = ["CUST-A01", "CUST-B07", "CUST-C12", "CUST-D03", "CUST-E21"]
    orders = []
    for pp in plant_products:
        for week in range(8):
            orders.append({"plant": pp["plant"], "model": pp["model"], "customer": str(rng.choice(customers)),
                           "qty": int(pp["weekly_demand"] * rng.uniform(0.8, 1.2)), "due_day": week * 7 + int(rng.integers(1, 7)),
                           "note": None})

    return {"sites": sites, "plants": plants, "suppliers": suppliers, "supplier_sites": supplier_sites, "contacts": contacts,
            "parts": parts, "sourcing": sourcing, "products": products, "bom": bom, "plant_products": plant_products,
            "inventory": inventory, "purchase_orders": pos, "customer_orders": orders}


def _moq(rng: np.random.Generator, unit_usd: float) -> int:
    # 越便宜的料件 MOQ 越大（MLCC、電阻論盤買）
    if unit_usd < 0.02:
        return int(rng.choice([10000, 15000, 20000]))
    if unit_usd < 0.5:
        return int(rng.choice([2000, 3000, 5000]))
    if unit_usd < 3:
        return int(rng.choice([500, 1000, 2000]))
    return int(rng.choice([100, 200, 500]))


TABLES = [(Site, "sites"), (Plant, "plants"), (Supplier, "suppliers"), (SupplierSite, "supplier_sites"), (Contact, "contacts"),
          (Part, "parts"), (Sourcing, "sourcing"), (Product, "products"), (BomLine, "bom"), (PlantProduct, "plant_products"),
          (Inventory, "inventory"), (PurchaseOrder, "purchase_orders"), (CustomerOrder, "customer_orders")]


def load(data: dict) -> None:
    with SessionLocal() as db:
        for model, _ in reversed(TABLES):
            db.execute(delete(model))
        for model, key in TABLES:
            rows = [{k: v for k, v in r.items() if k in model.__table__.columns} for r in data[key]]
            if rows:
                db.execute(insert(model), rows)
        db.commit()


def main() -> None:
    data = generate()
    load(data)
    out = settings.data_dir / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": SEED, **{k: len(v) for k, v in data.items()}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(manifest)


if __name__ == "__main__":
    main()
