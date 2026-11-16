const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];

export function roman(mmi: number | null): string {
  return mmi == null ? "—" : ROMAN[Math.max(1, Math.min(10, Math.round(mmi)))];
}

// 與 globals.css 的 --color-mmi-* 相同；地圖（Leaflet）要用實際色碼
const COLORS: Record<number, string> = { 4: "#80ffff", 5: "#7aff93", 6: "#ffff00", 7: "#ffc800", 8: "#ff9100", 9: "#ff0000", 10: "#c80000" };

// 顏色依等級區間（取整數部分），與影響判定的門檻一致
export function mmiColor(mmi: number | null): string {
  if (mmi == null) return "#c6cfd7";
  return COLORS[Math.max(4, Math.min(10, Math.floor(mmi)))];
}

export const LEVEL_LABEL: Record<string, string> = {
  severe_damage: "可能嚴重受損", damage_likely: "可能受損停工", disruption_possible: "可能短暫停工", check: "需要確認", none: "無明顯影響",
};

export const STATE: Record<string, { label: string; tone: "ok" | "wait" | "stop" | "idle" }> = {
  pending: { label: "尚未詢問", tone: "idle" },
  inquired: { label: "已寄出詢問", tone: "idle" },
  replied: { label: "已回覆", tone: "ok" },
  confirmed: { label: "已確認", tone: "ok" },
  needs_review: { label: "需人工確認", tone: "wait" },
  no_reply: { label: "逾時未回", tone: "stop" },
};

export const OPERATING: Record<string, string> = { normal: "正常", partial: "部分運作", stopped: "停工", unknown: "未知" };

export const COMMODITY: Record<string, string> = {
  semiconductor: "半導體", passive: "被動元件", magnetic: "磁性元件", pcb: "PCB", mechanical: "機構件", electromechanical: "連接器",
};

export function tPlus(hours: number): string {
  return hours < 48 ? `T+${hours}h` : `T+${Math.floor(hours / 24)}d ${hours % 24}h`;
}
