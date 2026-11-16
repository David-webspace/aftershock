"""用模型把三個方案的取捨寫成給主管看的文字說明。模型不選方案、不碰數字：

- 輸入只有求解器的結果（成本、缺料量、受影響訂單、動作清單）
- 說明裡不准出現數字：數字一律由程式從求解結果產生比較表。原本的做法是「數字必須出自結果」，
  但實測發現模型會把甲方案的成本寫成乙方案的（數字本身存在於結果中，檢查抓不到），所以改成完全不讓模型寫數字
- 違反就不採用，改用程式產生的比較說明；最後由人選方案，模型的建議只是參考
- 但文字敘述本身的對錯（例如把較貴的方案說成一樣貴）無法用程式檢查，本機小模型實測就寫錯過，
  所以預設顯示程式產生的 compare()；模型說明要經過評測（M6）才考慮開啟
"""

import json
import re

from app.llm import LLM

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
SMALL = 10  # 方案編號、「三個方案」這類小整數不檢查

SYSTEM = """你是採購主管的助理。下面是補救方案求解器的結果，請用繁體中文寫 3～5 句說明，讓主管快速決定：
- 三個方案的取捨：哪個比較省、哪個缺料比較少、差異來自哪些手段（追加訂單、空運、調撥、備援來源）
- 如果方案結果相同，直接說明原因（例如剩下的缺口沒有可用的手段）
- 不要寫任何數字或金額：數字會由系統另外以表格呈現，你只描述取捨與原因
- 不要承諾任何交期或數量；最後由主管決定"""

TOOL_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "suggested": {"type": "string", "enum": ["low_cost", "balanced", "min_shortage"]}},
    "required": ["summary", "suggested"]}


def _facts(opts: dict) -> dict:
    """給模型看的精簡版：每個方案的總數與動作，不含內部 ID。"""
    return {"horizon_days": opts["horizon_days"], "no_action": opts["no_action"], "options": [
        {"key": o["key"], "label": o["label"], "cost_usd": o["cost_usd"], "shortage_units": o["shortage_units"],
         "orders_at_risk": o["orders_at_risk"], "parts_still_short": o["parts_short"],
         "actions": [{"part": p["part_no"], "type": a["type"], "supplier": a.get("supplier"), "from": a.get("from"),
                      "plant": a.get("plant"), "mode": a.get("mode"), "qty": a["qty"], "cost_usd": a["cost_usd"]}
                     for p in o["plans"] for a in p["actions"]]} for o in opts["options"]]}


def ungrounded(text: str) -> list[str]:
    """說明中的數字（方案編號這類 10 以下的小整數除外）。不准出現，出現就不採用。"""
    return [n for n in NUM.findall(text) if not (float(n.replace(",", "")) <= SMALL and float(n.replace(",", "")).is_integer())]


def fallback(opts: dict) -> str:
    lines = [f"不採取行動：{opts['no_action']['stockouts']} 筆料件會斷料，影響客戶訂單 {opts['no_action']['orders_at_risk']} 張。"]
    for o in opts["options"]:
        lines.append(f"{o['label']}：額外成本 US${o['cost_usd']:,.2f}，剩餘缺料 {o['shortage_units']:,} 個，影響訂單 {o['orders_at_risk']} 張。")
    return "\n".join(lines)


def compare(opts: dict) -> str:
    """程式產生的比較說明（預設顯示這份）：只陳述從求解結果直接算得出的比較。"""
    o = {x["key"]: x for x in opts["options"]}
    lines = [fallback(opts), ""]
    cheapest = min(x["cost_usd"] for x in o.values())
    fewest = min(x["shortage_units"] for x in o.values())
    if len({(x["cost_usd"], x["shortage_units"], x["orders_at_risk"]) for x in o.values()}) == 1:
        lines.append("三個方案結果相同：不需要空運、調撥以外的付費手段或啟用備援來源，就能得到同樣的結果。")
        return "\n".join(lines)
    lines.append("成本最低：" + "、".join(x["label"] for x in o.values() if x["cost_usd"] == cheapest) + "。")
    lines.append("剩餘缺料最少：" + "、".join(x["label"] for x in o.values() if x["shortage_units"] == fewest) + "。")
    ms, bal = o["min_shortage"], o["balanced"]
    if ms["shortage_units"] == bal["shortage_units"] and ms["cost_usd"] > bal["cost_usd"]:
        lines.append(f"最少缺料方案比平衡方案多花 US${ms['cost_usd'] - bal['cost_usd']:,.2f}，缺料總量沒有減少，"
                     "只是把缺料往後延（較晚缺料的懲罰較輕）。")
    for pn, why in sorted(ms.get("gap_reasons", {}).items()):
        lines.append(f"{pn} 補不齊：{why}。")
    return "\n".join(lines)


def explain(llm: LLM | None, opts: dict) -> dict:
    facts = _facts(opts)
    if llm is None:
        return {"summary": compare(opts), "suggested": None, "source": "template", "note": None}
    ex = llm.extract(SYSTEM, json.dumps(facts, ensure_ascii=False), "write_summary", "寫下方案比較說明與建議方案", TOOL_SCHEMA)
    args = ex.args or {}
    # 有些相容端點的模型不照工具格式回傳、直接寫成文字：同樣接受，但一樣要通過不含數字的檢查
    summary = (args.get("summary") or ex.raw or "").strip()
    if not summary:
        return {"summary": compare(opts), "suggested": None, "source": "template", "note": "模型沒有回傳說明，改用固定格式"}
    bad = ungrounded(summary)
    if bad:
        return {"summary": compare(opts), "suggested": None, "source": "template",
                "note": f"模型的說明含有數字（{'、'.join(bad[:5])}），數字只能來自求解結果，改用固定格式"}
    suggested = args.get("suggested") if args.get("suggested") in ("low_cost", "balanced", "min_shortage") else None
    return {"summary": summary, "suggested": suggested, "source": ex.model, "note": None}
