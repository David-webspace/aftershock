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


def get(key: str) -> dict:
    s = all_scenarios()[key]
    ev = usgs.event(s["event_id"])
    return {**s, **{k: ev[k] for k in ("magnitude", "place", "lat", "lon", "depth_km", "max_mmi", "url")},
            "t0": datetime.fromtimestamp(ev["time_ms"] / 1000, TZ)}
