import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.ingest import usgs

FILE = Path(__file__).parent / "ingest" / "scenarios.yaml"
TZ = ZoneInfo("Asia/Taipei")


@lru_cache(maxsize=1)
def all_scenarios() -> dict[str, dict]:
    return {s["key"]: s for s in yaml.safe_load(FILE.read_text())}


LIVE = re.compile(r"^usgs:([a-z0-9]{6,40})$")


def is_valid(key: str) -> bool:
    return key in all_scenarios() or bool(LIVE.match(key))


def get(key: str) -> dict:
    m = LIVE.match(key)
    if m:
        # 即時事件：第一次用到時向 USGS 抓事件與 ShakeMap。事件 ID 只接受小寫英數字，會拿來組檔案路徑，不能讓 ../ 這類字元進來
        event_id = m.group(1)
        if not (usgs._dir(event_id) / "grid.npz").exists():
            usgs.fetch(event_id, live=True)
        ev = usgs.event(event_id)
        s = {"event_id": event_id, "key": key, "label": ev["title"], "note": "即時事件（USGS）"}
    else:
        s = all_scenarios()[key]
        ev = usgs.event(s["event_id"])
    return {**s, **{k: ev[k] for k in ("magnitude", "place", "lat", "lon", "depth_km", "max_mmi", "url")},
            "t0": datetime.fromtimestamp(ev["time_ms"] / 1000, TZ)}
