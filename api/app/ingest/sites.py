"""把 sites.yaml 的真實工業區查成座標（OpenStreetMap Nominatim，遵守每秒一次的使用政策），寫到 data/real/sites.json。

python -m app.ingest.sites            查詢尚未有座標的園區（已查過的沿用，不重打 API）
"""

import json
import time
from pathlib import Path

import httpx
import yaml

from app.config import settings

SRC = Path(__file__).with_name("sites.yaml")
OUT = settings.data_dir / "real" / "sites.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
# 查到的類別是園區本身（industrial、科學園區等），還是只到行政區
ESTATE_TYPES = {"industrial", "commercial", "retail", "science_park", "yes", "landuse", "business"}


def load() -> list[dict]:
    return json.loads(OUT.read_text())["sites"]


def _search(c: httpx.Client, params: dict) -> list:
    for attempt in range(4):
        time.sleep(1.1 * (attempt + 1))
        r = c.get(NOMINATIM, params=params)
        if r.status_code < 500:
            return r.raise_for_status().json()
    r.raise_for_status()
    return []


def run() -> None:
    done = {s["key"]: s for s in load()} if OUT.exists() else {}
    sites = []
    with httpx.Client(timeout=30, headers={"user-agent": "aftershock-research/0.1 (portfolio project)"}) as c:
        for spec in yaml.safe_load(SRC.read_text()):
            if spec["key"] in done:
                sites.append(done[spec["key"]])
                continue
            hit, used = None, None
            for q in spec["queries"]:
                # 限定國家：同名地點很多（「龍潭」「台中工業區」不限國家會查到中國、香港）
                r = _search(c, {"q": q, "format": "jsonv2", "limit": 1, "accept-language": "en", "countrycodes": spec["country"].lower()})
                if r and spec["area"].lower() in r[0]["display_name"].lower():
                    hit, used = r[0], q
                    break
            if hit is None:
                print("NOT FOUND", spec["key"], spec["queries"])
                continue
            precision = "estate" if hit.get("type") in ESTATE_TYPES or hit.get("category") == "landuse" else "city"
            sites.append({"key": spec["key"], "country": spec["country"], "name": spec["name"], "lat": round(float(hit["lat"]), 5),
                          "lon": round(float(hit["lon"]), 5), "precision": precision, "query": used,
                          "osm": f"{hit['osm_type']}/{hit['osm_id']}", "osm_name": hit["display_name"][:160]})
            print(spec["key"], precision, used, sites[-1]["lat"], sites[-1]["lon"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "© OpenStreetMap contributors, ODbL (via Nominatim)", "sites": sites},
                              ensure_ascii=False, indent=1))


if __name__ == "__main__":
    run()
