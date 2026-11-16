"""震度 → 影響等級。規則寫死在這裡，不交給模型判斷。

依 USGS 對修正麥卡利震度（MMI）的描述：VI「強：人人有感，重家具移動，輕微損害」、VII「很強：設計良好的建築
損害可忽略，一般建築輕至中度損害」、VIII「劇烈：一般建築相當程度損害」。電子料件廠多為低矮廠房，但精密設備
在 VI 就可能需要停機校正、檢查產線。

預估停工天數是規劃用的假設（不是預測），依過往公開報導的復工時間量級設定：震度 VI 等級多半數天內恢復，
強震重創的工廠則要數週到數月（例如 2011 年東日本地震中受創的半導體廠停工將近三個月）。用來推估斷料日；
收到供應商回覆後以實際狀況取代。

限制：MMI 反映不出長週期震波對高樓的放大（2025 緬甸地震時的曼谷即是一例）。供應商若在高樓層或特殊地盤，
需由人工調高等級。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    key: str
    label: str
    min_mmi: float
    planning_outage_days: int
    rank: int


LEVELS = [
    Level("severe_damage", "可能嚴重受損", 8.0, 90, 4),
    Level("damage_likely", "可能受損停工", 7.0, 42, 3),
    Level("disruption_possible", "可能短暫停工", 6.0, 5, 2),
    Level("check", "需要確認", 5.0, 0, 1),
]
NONE = Level("none", "無明顯影響", 0.0, 0, 0)
BY_KEY = {lv.key: lv for lv in [*LEVELS, NONE]}


def level_for(mmi: float | None) -> Level:
    if mmi is None:  # 不在 ShakeMap 範圍內：USGS 判斷沒有可感搖晃
        return NONE
    return next((lv for lv in LEVELS if mmi >= lv.min_mmi), NONE)
