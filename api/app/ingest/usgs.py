"""USGS 地震事件與 ShakeMap 震度網格（真實資料，美國政府公共領域）。

ShakeMap grid.xml 是規則網格，每格有 MMI（修正麥卡利震度）、PGA（%g）、PGV（cm/s），
綜合了測站實測與地動模型推估。原檔動輒數十 MB，這裡只留三個欄位壓成 npz，
任一座標用雙線性內插取值；超出網格範圍代表 USGS 判斷那裡沒有可感搖晃，回傳 None。

python -m app.ingest.usgs us7000m9g4 us7000pn9s ...   下載並存到 data/real/usgs/<event_id>/
"""

import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from app.config import settings

API = "https://earthquake.usgs.gov/fdsnws/event/1/query"
NS = {"s": "http://earthquake.usgs.gov/eqcenter/shakemap"}
FIELDS = ("MMI", "PGA", "PGV")
DIR = settings.data_dir / "real" / "usgs"
LIVE_DIR = settings.data_dir / "live" / "usgs"  # 執行時才抓的即時事件，不進 git


def _dir(event_id: str) -> Path:
    return DIR / event_id if (DIR / event_id).exists() else LIVE_DIR / event_id


def _client() -> httpx.Client:
    return httpx.Client(timeout=120, follow_redirects=True, headers={"user-agent": "aftershock-research/0.1"})


def fetch(event_id: str, live: bool = False) -> Path:
    out = (LIVE_DIR if live else DIR) / event_id
    out.mkdir(parents=True, exist_ok=True)
    with _client() as c:
        detail = c.get(API, params={"eventid": event_id, "format": "geojson"}).raise_for_status().json()
        p = detail["properties"]
        sm = p["products"]["shakemap"][0]
        files = sm["contents"]
        lon, lat, depth = detail["geometry"]["coordinates"]
        event = {
            "id": event_id, "title": p["title"], "place": p["place"], "magnitude": p["mag"], "time_ms": p["time"],
            "lat": lat, "lon": lon, "depth_km": depth, "url": p["url"],
            "shakemap_version": sm["properties"].get("version"), "max_mmi": float(sm["properties"].get("maxmmi", 0)),
            "pager_alert": p.get("alert"),
        }
        (out / "event.json").write_text(json.dumps(event, ensure_ascii=False, indent=1))
        (out / "cont_mmi.json").write_bytes(c.get(files["download/cont_mmi.json"]["url"]).raise_for_status().content)
        _save_grid(c.get(files["download/grid.xml"]["url"]).raise_for_status().content, out / "grid.npz")
    return out


def _save_grid(xml: bytes, path: Path) -> None:
    root = ET.fromstring(xml)
    spec = root.find("s:grid_specification", NS).attrib
    names = [f.attrib["name"] for f in sorted(root.findall("s:grid_field", NS), key=lambda f: int(f.attrib["index"]))]
    nlon, nlat = int(spec["nlon"]), int(spec["nlat"])
    rows = np.loadtxt(root.find("s:grid_data", NS).text.strip().splitlines(), dtype=np.float32)
    # grid_data 由北到南、由西到東排列；整理成 [lat(南→北), lon(西→東)]
    def field(name: str) -> np.ndarray:
        return rows[:, names.index(name)].reshape(nlat, nlon)[::-1]
    lons, lats = field("LON")[0], field("LAT")[:, 0]
    np.savez_compressed(path, lons=lons, lats=lats, **{f.lower(): field(f).astype(np.float32) for f in FIELDS})


@dataclass(frozen=True)
class Shaking:
    mmi: float
    pga_g: float  # 重力加速度的比例（0.1 = 0.1 g）
    pgv_cms: float


@lru_cache(maxsize=16)
def _grid(event_id: str) -> dict[str, np.ndarray]:
    with np.load(_dir(event_id) / "grid.npz") as z:
        return {k: z[k] for k in z.files}


def event(event_id: str) -> dict:
    return json.loads((_dir(event_id) / "event.json").read_text())


def shaking_at(event_id: str, lat: float, lon: float) -> Shaking | None:
    g = _grid(event_id)
    lats, lons = g["lats"], g["lons"]
    if not (lats[0] <= lat <= lats[-1] and lons[0] <= lon <= lons[-1]):
        return None
    i = int(np.clip(np.searchsorted(lats, lat) - 1, 0, len(lats) - 2))
    j = int(np.clip(np.searchsorted(lons, lon) - 1, 0, len(lons) - 2))
    ty = (lat - lats[i]) / (lats[i + 1] - lats[i])
    tx = (lon - lons[j]) / (lons[j + 1] - lons[j])

    def interp(a: np.ndarray) -> float:
        return float((a[i, j] * (1 - tx) + a[i, j + 1] * tx) * (1 - ty) + (a[i + 1, j] * (1 - tx) + a[i + 1, j + 1] * tx) * ty)

    return Shaking(round(interp(g["mmi"]), 2), round(interp(g["pga"]) / 100, 4), round(interp(g["pgv"]), 2))


if __name__ == "__main__":
    for eid in sys.argv[1:]:
        print(fetch(eid))
