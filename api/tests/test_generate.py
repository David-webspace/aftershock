"""合成資料：可重現、只用真實園區、不寄真實信箱、不撞知名業者、每個 BOM 料件都有合格來源。"""

from collections import defaultdict

from app.seed.generate import FAMOUS, generate


def test_reproducible():
    a, b = generate(), generate()
    assert a["suppliers"] == b["suppliers"] and a["purchase_orders"][:50] == b["purchase_orders"][:50]


def test_integrity():
    d = generate()
    real_sites = {s["key"] for s in d["sites"]}
    assert all(ss["site_key"] in real_sites for ss in d["supplier_sites"])
    assert all(p["site_key"] in real_sites for p in d["plants"])
    assert all(c["email"].endswith(".example") for c in d["contacts"])
    assert not any(f in s["name"].lower() for s in d["suppliers"] for f in FAMOUS)

    qualified = defaultdict(list)
    for s in d["sourcing"]:
        if s["qualified"]:
            qualified[s["part_no"]].append(s["share_pct"])
    assert all(b["part_no"] in qualified for b in d["bom"])
    assert all(sum(v) == 100 for v in qualified.values())
    assert any(len(v) == 1 for v in qualified.values())  # 有單一來源料件，斷料情境才有意義
