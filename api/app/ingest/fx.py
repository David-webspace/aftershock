"""各情境發生日的實際匯率（以美元為基準）。

- 新台幣：美國聯準會 FRED 序列 DEXTAUS（台幣兌美元，日資料）
- 其他：歐洲央行參考匯率（經 Frankfurter API）
歐洲央行沒有越南盾；越南供應商以美元報價（實務上常見），不需換算。
遇假日沒有報價時，取前一個有報價的營業日。

python -m app.ingest.fx
"""

import csv
import io
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx
import yaml

from app.config import settings
from app.ingest.usgs import DIR as USGS_DIR

OUT = settings.data_dir / "real" / "fx.json"
SCENARIOS = Path(__file__).with_name("scenarios.yaml")
CURRENCIES = ["JPY", "CNY", "THB", "MYR", "PHP", "MXN", "IDR"]


def _twd(c: httpx.Client, day: date) -> tuple[str, float]:
    text = c.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                 params={"id": "DEXTAUS", "cosd": (day - timedelta(days=10)).isoformat(), "coed": day.isoformat()}).raise_for_status().text
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r["DEXTAUS"] not in ("", ".")]
    return rows[-1]["observation_date"], float(rows[-1]["DEXTAUS"])


def run() -> None:
    out = {"source": "TWD: FRED DEXTAUS (Board of Governors of the Federal Reserve System); others: ECB reference rates via frankfurter.app",
           "base": "USD", "rates": {}}
    with httpx.Client(timeout=60, follow_redirects=True, headers={"user-agent": "aftershock-research/0.1"}) as c:
        for s in yaml.safe_load(SCENARIOS.read_text()):
            ev = json.loads((USGS_DIR / s["event_id"] / "event.json").read_text())
            day = datetime.fromtimestamp(ev["time_ms"] / 1000, ZoneInfo("Asia/Taipei")).date()  # 採購方在台灣，以台北日期為準
            ecb = c.get(f"https://api.frankfurter.app/{day.isoformat()}", params={"from": "USD", "to": ",".join(CURRENCIES)}).raise_for_status().json()
            twd_day, twd = _twd(c, day)
            out["rates"][s["key"]] = {"event_date": day.isoformat(), "ecb_date": ecb["date"], "twd_date": twd_day,
                                      "per_usd": {"USD": 1.0, "TWD": twd, **ecb["rates"]}}
            print(s["key"], out["rates"][s["key"]])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    run()
