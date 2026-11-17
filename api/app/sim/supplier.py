"""模擬供應商：依震度等級產生各廠區的「實際狀況」，並依狀況用供應商的語言寫回信。

實際狀況只存在 sim_truth 表，給模擬器與評測用，API 與解析回信的模型都讀不到；評測拿它檢查模型解析得對不對。
回信刻意有不同風格，考驗解析：
- complete：狀態、損害、恢復日期、產能都講清楚
- partial：講了狀態與損害，恢復日期「還在評估」→ 應判定需要人工確認或追問
- vague：只說「正在確認，稍後回覆」→ 不能當成正常
- silent：第一封不回，被追問後才完整回覆
另有一部分供應商會在詢問之前主動通報（notice），見檔案後段。
同一個（情境、供應商、廠區）每次產生的結果相同，評測可重現。
"""

import zlib
from datetime import date, timedelta

import numpy as np

STYLES = (("complete", 0.55), ("partial", 0.15), ("vague", 0.10), ("silent", 0.20))


def _rng(*keys: str) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32("|".join(keys).encode()))


def truth(scenario_key: str, supplier_id: str, site_key: str, level: str) -> dict:
    r = _rng(scenario_key, supplier_id, site_key)
    if level in ("severe_damage", "damage_likely"):
        if r.random() < 0.7:
            return {"operating": "stopped", "capacity_pct": 0, "resume_day": int(r.integers(21, 76)), "damage": "structure"}
        return {"operating": "partial", "capacity_pct": int(r.integers(3, 7)) * 10, "resume_day": int(r.integers(14, 41)), "damage": "equipment"}
    if level == "disruption_possible":
        x = r.random()
        if x < 0.5:
            return {"operating": "stopped", "capacity_pct": 0, "resume_day": int(r.integers(1, 5)), "damage": "inspection"}
        if x < 0.8:
            return {"operating": "partial", "capacity_pct": int(r.integers(6, 10)) * 10, "resume_day": int(r.integers(2, 8)), "damage": "inspection"}
        return {"operating": "normal", "capacity_pct": 100, "resume_day": 0, "damage": "none"}
    if r.random() < 0.85:
        return {"operating": "normal", "capacity_pct": 100, "resume_day": 0, "damage": "none"}
    return {"operating": "partial", "capacity_pct": int(r.integers(8, 10)) * 10, "resume_day": int(r.integers(1, 4)), "damage": "inspection"}


def style(scenario_key: str, supplier_id: str) -> str:
    r = _rng("style", scenario_key, supplier_id)
    names, p = zip(*STYLES)
    return str(r.choice(names, p=p))


def delay_hours(scenario_key: str, supplier_id: str, worst: str) -> int:
    r = _rng("delay", scenario_key, supplier_id)
    lo, hi = {"stopped": (8, 30), "partial": (4, 20), "normal": (2, 12)}[worst]
    return int(r.integers(lo, hi + 1))


# ── 回信文字 ─────────────────────────────────────────────

def _d(lang: str, d: date) -> str:
    return {"zh-TW": f"{d.month}月{d.day}日", "zh-CN": f"{d.month}月{d.day}日", "ja": f"{d.month}月{d.day}日",
            "en": d.strftime("%B %-d")}[lang]


DAMAGE = {
    "structure": {"zh-TW": "部分廠房結構受損，無塵室需要重新認證", "zh-CN": "部分厂房结构受损，无尘室需要重新认证",
                  "ja": "建屋の一部に損傷があり、クリーンルームの再認定が必要です", "en": "part of the building structure is damaged and the cleanroom needs requalification"},
    "equipment": {"zh-TW": "多台生產設備位移，需重新校正", "zh-CN": "多台生产设备位移，需重新校正",
                  "ja": "複数の生産設備がずれており、再調整が必要です", "en": "several production machines shifted and need recalibration"},
    "inspection": {"zh-TW": "產線緊急停機，正在逐台檢查設備", "zh-CN": "产线紧急停机，正在逐台检查设备",
                   "ja": "生産ラインを緊急停止し、設備を順次点検しています", "en": "the lines were stopped for safety and equipment is being inspected"},
    "none": {"zh-TW": "沒有發現損害", "zh-CN": "没有发现损害", "ja": "損傷は確認されていません", "en": "no damage was found"},
}


def _site_text(lang: str, site_name: str, t: dict, t0: date, show_resume: bool, variant: int) -> str:
    dmg = DAMAGE[t["damage"]][lang]
    resume = _d(lang, t0 + timedelta(days=t["resume_day"]))
    cap = t["capacity_pct"]
    if t["operating"] == "normal":
        return [{"zh-TW": f"{site_name}：人員平安，{dmg}，目前正常生產，出貨不受影響。",
                 "zh-CN": f"{site_name}：人员平安，{dmg}，目前正常生产，出货不受影响。",
                 "ja": f"{site_name}：従業員は全員無事で、{dmg}。通常どおり稼働しており、出荷への影響はございません。",
                 "en": f"{site_name}: all staff are safe and {dmg}. We are operating normally and shipments are not affected."},
                {"zh-TW": f"{site_name}已完成巡檢，{dmg}，產線運作正常，訂單照原訂日期出貨。",
                 "zh-CN": f"{site_name}已完成巡检，{dmg}，产线运作正常，订单按原定日期出货。",
                 "ja": f"{site_name}は点検を完了し、{dmg}。ラインは正常に稼働しており、ご注文は予定どおり出荷いたします。",
                 "en": f"We have completed checks at {site_name}; {dmg}. Production is normal and orders will ship as scheduled."}][variant][lang]
    if t["operating"] == "stopped":
        when = ({"zh-TW": f"預計 {resume} 恢復出貨", "zh-CN": f"预计 {resume} 恢复出货", "ja": f"出荷再開は{resume}頃の見込みです",
                 "en": f"we expect to resume shipments around {resume}"} if show_resume else
                {"zh-TW": "恢復時間還在評估", "zh-CN": "恢复时间还在评估", "ja": "再開時期は現在精査中です", "en": "the recovery timeline is still being assessed"})[lang]
        return {"zh-TW": f"{site_name}：{dmg}，目前全面停工，{when}。", "zh-CN": f"{site_name}：{dmg}，目前全面停工，{when}。",
                "ja": f"{site_name}：{dmg}。現在、全面的に稼働を停止しており、{when}。",
                "en": f"{site_name}: {dmg}. Operations are fully stopped for now, and {when}."}[lang]
    when = ({"zh-TW": f"預計 {resume} 恢復正常產能", "zh-CN": f"预计 {resume} 恢复正常产能", "ja": f"{resume}頃に通常の生産能力へ戻る見込みです",
             "en": f"we expect full capacity again around {resume}"} if show_resume else
            {"zh-TW": "何時恢復正常還不確定", "zh-CN": "何时恢复正常还不确定", "ja": "通常稼働への復帰時期はまだ未定です", "en": "we cannot yet say when full capacity will return"})[lang]
    return {"zh-TW": f"{site_name}：{dmg}，目前部分產線恢復，產能約 {cap}%，{when}。",
            "zh-CN": f"{site_name}：{dmg}，目前部分产线恢复，产能约 {cap}%，{when}。",
            "ja": f"{site_name}：{dmg}。一部のラインは再開しており、稼働率は約{cap}%です。{when}。",
            "en": f"{site_name}: {dmg}. Some lines are back and we are running at about {cap}% capacity; {when}."}[lang]


GREET = {"zh-TW": "您好，感謝關心。", "zh-CN": "您好，感谢关心。", "ja": "ご連絡ありがとうございます。", "en": "Hello, and thank you for checking in."}
VAGUE = {"zh-TW": "我們正在確認各廠區狀況，確認後會再回覆您。", "zh-CN": "我们正在确认各厂区状况，确认后会再回复您。",
         "ja": "現在、各拠点の状況を確認しております。確認でき次第、改めてご連絡いたします。",
         "en": "We are still checking the situation at our sites and will get back to you once we know more."}
SIGN = {"zh-TW": "敬祝 平安", "zh-CN": "此致", "ja": "よろしくお願いいたします。", "en": "Best regards,"}


def reply_body(lang: str, contact: str, style_key: str, sites: list[tuple[str, dict]], t0: date, variant: int) -> str:
    if style_key == "vague":
        parts = [VAGUE[lang]]
    else:
        parts = [_site_text(lang, name, t, t0, style_key != "partial", variant) for name, t in sites]
    return "\n\n".join([GREET[lang], *parts, f"{SIGN[lang]}\n{contact}"])


# ── 主動通報：沒等我們詢問，供應商自己寄來的狀況說明 ─────────────────
# 受災越重越可能主動通報；通報多半在震後半天內，早於詢問信的回覆

PROACTIVE = {"severe_damage": 0.6, "damage_likely": 0.6, "disruption_possible": 0.4, "check": 0.2}


def proactive_hour(scenario_key: str, supplier_id: str, worst_level: str) -> int | None:
    r = _rng("proactive", scenario_key, supplier_id)
    if r.random() >= PROACTIVE[worst_level]:
        return None
    return int(r.integers(2, 13))


def notice_style(scenario_key: str, supplier_id: str) -> str:
    # 震後頭幾個小時常常還不知道何時恢復：三成的通報只說狀態、沒有恢復日期
    return "complete" if _rng("notice-style", scenario_key, supplier_id).random() < 0.7 else "partial"


NOTICE_SUBJECT = {"zh-TW": "【地震影響通報】{company}", "zh-CN": "【地震影响通报】{company}", "ja": "【地震影響のご報告】{company}",
                  "en": "Earthquake impact notice from {company}"}
NOTICE_OPEN = {
    "zh-TW": "各位客戶您好：\n\n{when}發生的地震，本公司已完成初步盤點，各廠區狀況通報如下。",
    "zh-CN": "各位客户您好：\n\n{when}发生的地震，本公司已完成初步盘点，各厂区状况通报如下。",
    "ja": "お客様各位\n\n{when}に発生した地震について、弊社拠点の初期確認が完了しましたので、状況をご報告いたします。",
    "en": "Dear valued customer,\n\nFollowing the earthquake on {when}, we have completed an initial check of our facilities. Here is the current status.",
}
NOTICE_CLOSE = {"zh-TW": "後續如有變化，將再主動通知。", "zh-CN": "后续如有变化，将再主动通知。",
                "ja": "状況に変化がございましたら、改めてご連絡いたします。", "en": "We will update you if anything changes."}


def notice(lang: str, company: str, contact: str, style_key: str, sites: list[tuple[str, dict]], t0: date, variant: int) -> tuple[str, str]:
    parts = [_site_text(lang, name, t, t0, style_key != "partial", variant) for name, t in sites]
    body = "\n\n".join([NOTICE_OPEN[lang].format(when=_d(lang, t0)), *parts, NOTICE_CLOSE[lang], f"{SIGN[lang]}\n{contact}\n{company}"])
    return NOTICE_SUBJECT[lang].format(company=company), body
