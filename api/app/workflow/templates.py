"""詢問信與追問信範本（依供應商語言）。內容固定、只填事實欄位，不讓模型起草：對外信件不會冒出未經核准的承諾。"""

from datetime import date

SUBJECT = {
    "zh-TW": "[{token}] 地震影響確認：{label}",
    "zh-CN": "[{token}] 地震影响确认：{label}",
    "ja": "[{token}] 地震による影響のご確認：{label}",
    "en": "[{token}] Earthquake impact check: {label}",
}
FOLLOW_SUBJECT = {
    "zh-TW": "[{token}] 再次確認：地震影響（{label}）",
    "zh-CN": "[{token}] 再次确认：地震影响（{label}）",
    "ja": "[{token}] 再度のご確認：地震の影響（{label}）",
    "en": "[{token}] Follow-up: earthquake impact ({label})",
}

INTRO = {
    "zh-TW": "{contact} 您好：\n\n{when}發生 {place} 規模 {mag} 地震。依美國地質調查所（USGS）的震度資料，貴公司以下廠區可能受到影響，想確認目前狀況：",
    "zh-CN": "{contact} 您好：\n\n{when}发生 {place} 规模 {mag} 地震。根据美国地质调查局（USGS）的烈度资料，贵司以下厂区可能受到影响，想确认目前状况：",
    "ja": "{contact} 様\n\nいつもお世話になっております。{when}に {place} でマグニチュード {mag} の地震が発生しました。USGS の震度データによると、貴社の下記拠点が影響を受けた可能性がございます。現状をご確認させてください。",
    "en": "Dear {contact},\n\nA magnitude {mag} earthquake occurred {where} on {when}. Based on USGS shaking data, the following facilities of yours may have been affected, and we would like to confirm their current status:",
}
QUESTIONS = {
    "zh-TW": ["廠區與人員目前狀況（正常運作／部分運作／停工）", "是否有設備或廠房損害", "預計恢復正常出貨的日期", "目前可用產能大約幾成",
              "下列料號的未交訂單，出貨日期是否受影響"],
    "zh-CN": ["厂区与人员目前状况（正常运作／部分运作／停工）", "是否有设备或厂房损害", "预计恢复正常出货的日期", "目前可用产能大约几成",
              "下列料号的未交订单，出货日期是否受影响"],
    "ja": ["拠点および従業員の現状（通常稼働／一部稼働／停止）", "設備・建屋の損傷の有無", "通常出荷再開の見込み日", "現在の稼働率の目安",
           "下記品番の未納注文について、出荷日への影響の有無"],
    "en": ["Current status of the facility and staff (normal / partial operation / stopped)", "Any damage to equipment or buildings",
           "Expected date to resume normal shipments", "Approximate current capacity (%)",
           "Whether shipment dates for open orders of the parts below are affected"],
}
PARTS_HEAD = {"zh-TW": "相關料號（未來 30 天到期的未交訂單）：", "zh-CN": "相关料号（未来 30 天到期的未交订单）：",
              "ja": "対象品番（今後 30 日以内に納期を迎える未納注文）：", "en": "Parts concerned (open orders due in the next 30 days):"}
PART_LINE = {"zh-TW": "- {pn}：{n} 張訂單，共 {qty:,} 個", "zh-CN": "- {pn}：{n} 张订单，共 {qty:,} 个",
             "ja": "- {pn}：注文 {n} 件、計 {qty:,} 個", "en": "- {pn}: {n} orders, {qty:,} pcs in total"}
CLOSE = {
    "zh-TW": "若尚無法確定，也請先回覆目前已知的部分，我們會持續追蹤。謝謝！\n\nArcwell Electronics 採購部\n{buyer}",
    "zh-CN": "如暂时无法确定，也请先回复目前已知的部分，我们会持续跟进。谢谢！\n\nArcwell Electronics 采购部\n{buyer}",
    "ja": "未確定の点がございましても、現時点で分かる範囲でご回答いただけますと幸いです。何卒よろしくお願い申し上げます。\n\nArcwell Electronics 購買部\n{buyer}",
    "en": "If anything is still unknown, please reply with what you know so far and we will follow up. Thank you.\n\nBest regards,\n{buyer}\nProcurement, Arcwell Electronics",
}
FOLLOW_INTRO = {
    "zh-TW": "{contact} 您好：\n\n先前詢問的地震影響尚未收到回覆。想再次確認以下廠區的狀況，尤其是預計恢復出貨的日期：",
    "zh-CN": "{contact} 您好：\n\n先前询问的地震影响尚未收到回复。想再次确认以下厂区的状况，尤其是预计恢复出货的日期：",
    "ja": "{contact} 様\n\n先日お問い合わせした地震の影響について、まだご回答をいただけておりません。下記拠点の状況、特に出荷再開の見込み日について改めてご確認させてください。",
    "en": "Dear {contact},\n\nWe have not yet received a reply to our earlier inquiry about the earthquake. Could you please confirm the status of the facilities below, especially the expected date to resume shipments?",
}


def when_text(lang: str, d: date) -> str:
    return {"zh-TW": f"{d.month} 月 {d.day} 日", "zh-CN": f"{d.month} 月 {d.day} 日", "ja": f"{d.month}月{d.day}日",
            "en": d.strftime("%B %-d, %Y")}[lang]


def render(kind: str, lang: str, *, token: str, label: str, contact: str, place: str, mag: float, event_date: date,
           sites: list[str], parts: list[dict], buyer: str) -> tuple[str, str]:
    if kind == "inquiry":
        subject = SUBJECT[lang].format(token=token, label=label)
        intro = INTRO[lang].format(contact=contact, when=when_text(lang, event_date), place=place, mag=mag, where=f"near {place}")
    else:
        subject = FOLLOW_SUBJECT[lang].format(token=token, label=label)
        intro = FOLLOW_INTRO[lang].format(contact=contact)
    lines = [intro, "", *[f"・{s}" for s in sites], ""]
    lines += [f"{i}. {q}" for i, q in enumerate(QUESTIONS[lang], 1)]
    if parts:
        lines += ["", PARTS_HEAD[lang], *[PART_LINE[lang].format(**p) for p in parts]]
    lines += ["", CLOSE[lang].format(buyer=buyer)]
    return subject, "\n".join(lines)
