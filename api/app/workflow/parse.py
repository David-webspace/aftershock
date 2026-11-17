"""把供應商回信解析成各廠區的結構化狀態。模型負責讀信，程式負責驗證；驗證不過的一律交給人確認，不會自動寫進曝險計算。

驗證規則：
- 每個廠區的判斷都要附「逐字摘自信件」的依據；依據不在信裡，視為模型自己編的，該廠區交人確認
- 停工或部分運作卻沒有恢復日期、或日期不合理（早於地震或一年以後），交人確認
- 狀態與數字互相矛盾（部分運作卻沒有產能、正常卻產能不足或還有恢復日、停工卻還有產能），交人確認：
  依據檢查只能抓到捏造，抓不到「引用正確但判讀錯誤」（例如依據寫全面停工、狀態卻填部分運作），這層補的是後者
- 同一廠區回了多筆且內容不一致，交人確認（只取第一筆的話，夾帶指令寫出的那筆排在前面就會被採用）
- 信中沒提到的廠區維持未知
"""

import re
from datetime import date

from app.llm import LLM

TOOL = "record_supplier_status"
DESCRIPTION = "記錄供應商回信中，各廠區的現況。只能填信件中明確寫到的內容。"
SYSTEM = """你負責把供應商回覆的地震影響說明整理成結構化資料。規則：
- 只根據信件內容；信中沒寫到的就填 unknown 或 null，不要推測或補上常理判斷。
- operating：normal（正常生產、出貨不受影響）、partial（部分運作）、stopped（停工）、unknown（沒說清楚，例如「還在確認」）。
- resume_date：恢復正常出貨或正常產能的日期，轉成 YYYY-MM-DD。信中只寫月日時，年份用地震發生的年份；若該月日早於地震日期，用下一年。沒寫就填 null。
- capacity_pct：目前產能百分比；正常運作填 100；沒寫填 null。
- evidence：從信件「逐字複製」支持這個判斷的一句話，不可改寫或翻譯。
- 每個列出的廠區都要回傳一筆。"""


def schema(site_keys: list[str]) -> dict:
    return {"type": "object", "properties": {"sites": {"type": "array", "items": {"type": "object", "properties": {
        "site_key": {"type": "string", "enum": site_keys},
        "operating": {"type": "string", "enum": ["normal", "partial", "stopped", "unknown"]},
        "capacity_pct": {"type": ["integer", "null"]},
        "resume_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "damage": {"type": ["string", "null"], "description": "損害摘要，用信件的語言"},
        "evidence": {"type": "string"}},
        "required": ["site_key", "operating", "capacity_pct", "resume_date", "evidence"]}}}, "required": ["sites"]}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def parse(llm: LLM, body: str, t0: date, sites: list[dict]) -> dict:
    """sites：[{key, name, name_en}]。回傳 {"sites": {key: {...}}, "issues": [...], "model", "tokens"}。"""
    listing = "\n".join(f"- {s['key']}：{s['name']}（{s['name_en']}）" for s in sites)
    user = f"地震發生日期：{t0.isoformat()}\n\n詢問的廠區：\n{listing}\n\n供應商回信：\n<信件>\n{body}\n</信件>"
    ex = llm.extract(SYSTEM, user, TOOL, DESCRIPTION, schema([s["key"] for s in sites]))
    result = {"model": ex.model, "tokens": [ex.input_tokens, ex.output_tokens], "sites": {}, "issues": []}
    if not ex.args or not isinstance(ex.args.get("sites"), list):
        result["issues"].append("模型沒有回傳可用的結構化結果")
        return result
    known = {s["key"] for s in sites}
    for item in ex.args["sites"]:
        key = item.get("site_key")
        if key not in known:
            continue
        r = _validate(item, body, t0)
        prev = result["sites"].get(key)
        if prev is None:
            result["sites"][key] = r
        elif (prev["operating"], prev["resume_day"]) != (r["operating"], r["resume_day"]) and "同一廠區有互相矛盾的判斷" not in prev["issues"]:
            prev["issues"].append("同一廠區有互相矛盾的判斷")
            prev["usable"] = False
    for key in known - set(result["sites"]):
        result["sites"][key] = {"operating": "unknown", "capacity_pct": None, "resume_day": None, "damage": None, "evidence": None,
                                "usable": False, "issues": ["信中沒有提到這個廠區"]}
    return result


def _validate(item: dict, body: str, t0: date) -> dict:
    issues = []
    op = item.get("operating") if item.get("operating") in ("normal", "partial", "stopped", "unknown") else "unknown"
    evidence = (item.get("evidence") or "").strip()
    if not evidence or _norm(evidence) not in _norm(body):
        issues.append("判斷依據不在信件原文中")
    cap = item.get("capacity_pct")
    if cap is not None and not (isinstance(cap, int) and 0 <= cap <= 100):
        issues.append("產能數字不合理")
        cap = None
    resume_day = None
    if item.get("resume_date"):
        try:
            resume_day = (date.fromisoformat(item["resume_date"]) - t0).days
        except ValueError:
            issues.append("恢復日期格式無法辨識")
        else:
            if not 0 <= resume_day <= 365:
                issues.append("恢復日期早於地震或在一年以後")
                resume_day = None
    if op == "normal":
        if (cap is not None and cap < 100) or (resume_day or 0) > 0:
            issues.append("判定正常，但產能或恢復日期顯示尚未完全恢復")
        resume_day, cap = 0, 100
    elif op in ("stopped", "partial") and resume_day is None:
        issues.append("沒有恢復日期")
    elif op == "unknown":
        issues.append("供應商尚未說明現況")
    if op == "partial" and (cap is None or not 0 < cap < 100):
        issues.append("判定部分運作，但沒有 1～99% 的產能數字")
    if op == "stopped":
        if cap:
            issues.append("判定停工，但填了產能")
        cap = 0
    return {"operating": op, "capacity_pct": cap, "resume_day": resume_day, "damage": item.get("damage"), "evidence": evidence,
            "usable": not issues, "issues": issues}
