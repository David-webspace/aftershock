"""ShakeMap 內插：在網格點上等於原值、超出網格回 None，並符合真實事件的已知分布。"""

from app.ingest.usgs import _grid, event, shaking_at

HUALIEN = "us7000m9g4"


def test_grid_node_returns_exact_value():
    g = _grid(HUALIEN)
    i, j = 300, 400
    s = shaking_at(HUALIEN, float(g["lats"][i]), float(g["lons"][j]))
    assert abs(s.mmi - float(g["mmi"][i, j])) < 0.01


def test_outside_grid_is_none():
    assert shaking_at(HUALIEN, 35.68, 139.76) is None  # 東京，不在花蓮地震的 ShakeMap 範圍內


def test_real_event_ordering():
    # 越接近震央越強；花蓮市高於新竹、新竹高於高雄
    near, mid, far = (shaking_at(HUALIEN, *ll).mmi for ll in [(23.99, 121.60), (24.78, 121.0), (22.62, 120.30)])
    assert near > mid > far
    assert event(HUALIEN)["magnitude"] == 7.4


def test_distance_alone_is_not_enough():
    # 緬甸 M7.7：泰國北部南奔（震央約 600 km）仍比東部 Amata City（約 900 km）有感，但兩者都遠低於曼德勒
    mandalay, lamphun, chonburi = (shaking_at("us7000pn9s", *ll).mmi for ll in [(21.97, 96.08), (18.59, 99.05), (13.45, 101.08)])
    assert mandalay > 8 > lamphun > chonburi
