"""產生 eval/REPORT.md：確定性驗證（每次重算）＋回信解析評測（彙整 eval/parsing-*.json）。

python -m app.evals.report
"""

import json
from collections import Counter
from pathlib import Path

from app.db import SessionLocal
from app.evals import oracle
from app.impact.exposure import assess
from app.plan.solver import HORIZON, PROFILES, build, solve
from app.scenarios import all_scenarios

OUT = Path(__file__).resolve().parents[2] / "eval"
STYLE = {"complete": "完整", "partial": "只說一半", "vague": "含糊", "injection": "夾帶指令", "relative_date": "相對日期", "notice": "主動通報"}


def exposure_rows() -> list[str]:
    rows = ["| 情境 | 受影響廠區 | 工廠×料件 | 與標準答案一致 | 地震造成斷料 |", "|---|---|---|---|---|"]
    with SessionLocal() as db:
        for key, s in all_scenarios().items():
            a = assess(db, key)
            want = oracle.expected(s["event_id"])
            got = {(e.plant, e.part_no): e for e in a.exposures}
            same = sum(1 for k, w in want.items() if k in got and (got[k].level.key, got[k].stockout_day, got[k].baseline_stockout_day,
                                                                      got[k].at_risk_po_qty) == (w["level"], w["stockout_day"],
                                                                                                 w["baseline_stockout_day"], w["at_risk_po_qty"]))
            match = f"{same}/{len(want)}" + ("" if set(got) == set(want) else "（集合不同）")
            rows.append(f"| {s['label']} | {sum(1 for x in a.sites if x.level.rank)} | {len(a.exposures)} | {match} | "
                        f"{sum(1 for e in a.exposures if e.quake_caused)} |")
    return rows


def solver_rows() -> list[str]:
    rows = ["| 情境 | 料件 | 不行動時斷料日與曝險一致 | 三個方案求得最佳解 |", "|---|---|---|---|"]
    with SessionLocal() as db:
        for key in ("hualien-2024", "tohoku-2011"):
            a = assess(db, key, horizon=HORIZON)
            parts = sorted({e.part_no for e in a.exposures if e.quake_caused})
            consistent = total = optimal = 0
            for pn in parts:
                pb = build(db, a, pn)
                none = solve(pb, "none")
                for e in (e for e in a.exposures if e.quake_caused and e.part_no == pn):
                    total += 1
                    consistent += none.first_short_day[e.plant] == e.stockout_day
                optimal += sum(solve(pb, p).status == "optimal" for p in PROFILES)
            rows.append(f"| {all_scenarios()[key]['label']} | {len(parts)} | {consistent}/{total} | {optimal}/{len(parts) * 3} |")
    return rows


def parsing_rows() -> list[str]:
    files = sorted(OUT.glob("parsing-*.json"))
    if not files:
        return ["尚未執行。"]
    rows = ["| 模型 | 回信 | 廠區判斷 | 自動採用且正確 | **自動採用但錯誤** | 該交人確認的交人確認 | 多交人確認 | 平均秒數 |",
            "|---|---|---|---|---|---|---|---|"]
    detail = []
    for f in files:
        d = json.loads(f.read_text())
        s, v = d["summary"], Counter(d["summary"]["verdicts"])
        rows.append(f"| {s['model']} | {s['replies']} | {s['sites']} | {v['auto_correct']} | **{v['auto_wrong']}** | {v['review_ok']} | "
                    f"{v['review_extra']} | {s['avg_seconds']} |")
        detail.append(f"\n**{s['model']}：依回信風格**\n")
        detail.append("| 風格 | 自動採用且正確 | 自動採用但錯誤 | 交人確認（應該） | 多交人確認 |")
        detail.append("|---|---|---|---|---|")
        for st in ("complete", "partial", "vague", "injection", "relative_date", "notice"):
            c = Counter(s["by_style"].get(st, {}))
            if c:
                detail.append(f"| {STYLE[st]} | {c['auto_correct']} | {c['auto_wrong']} | {c['review_ok']} | {c['review_extra']} |")
        wrong = [(r, x) for r in d["rows"] for x in r["sites"] if x["verdict"] == "auto_wrong"]
        if wrong:
            detail.append("\n自動採用但錯誤的案例：\n")
            for r, x in wrong:
                detail.append(f"- {r['scenario']} {r['supplier']}（{r['language']}，{STYLE[r['style']]}）{x['site']}："
                              f"應為 {x['expect']['operating']}／第 {x['expect']['resume_day']} 天，解析成 {x['got']['operating']}／第 {x['got']['resume_day']} 天")
    return rows + detail


def main() -> None:
    lines = ["# 評測報告", "",
             "## 1. 影響判定與曝險（確定性）", "",
             "標準答案由 `app/evals/oracle.py` 以 pandas＋scipy 依同一份規格另外實作（震度內插也是獨立實作），不經過被測模組。", "",
             *exposure_rows(), "",
             "## 2. 補救方案求解器（確定性）", "",
             "「不行動」時求解器算出的第一個缺料日，必須與曝險計算一致；另有測試逐日重播每個方案確認可行，"
             "並以小型問題的暴力搜尋（4⁹ 種組合）確認最佳值相同（`tests/test_plan.py`）。", "",
             *solver_rows(), "",
             "## 3. 供應商回信解析（模型）", "",
             "評測集：六起真實地震的受影響供應商，每家三種回信（完整、只說一半、含糊），另加夾帶指令與相對日期兩類刁難題，"
             "以及會主動通報的供應商寄來的通報信；"
             "實際狀況由模擬器產生，模型讀不到（`app/evals/parsing.py`）。"
             "「自動採用但錯誤」最危險：錯的數字會直接進曝險計算；「多交人確認」安全但多了人工。", "",
             *parsing_rows(), ""]
    OUT.mkdir(exist_ok=True)
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
