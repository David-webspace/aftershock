import { mmiColor, roman } from "@/lib/mmi";
import type { SiteImpact } from "@/lib/types";

// 震度尺：IV～X 的刻度上，標出每個受影響廠區實際受到的震度（自有工廠以方塊表示）
export function MmiRuler({ sites }: { sites: SiteImpact[] }) {
  const lo = 4, hi = 10;
  const pos = (m: number) => `${((Math.min(hi, Math.max(lo, m)) - lo) / (hi - lo)) * 100}%`;
  const thresholds = [{ m: 5, t: "需確認" }, { m: 6, t: "可能短暫停工" }, { m: 7, t: "可能受損" }, { m: 8, t: "可能嚴重受損" }];
  return (
    <figure className="min-w-0">
      <div className="relative h-12">
        {sites.filter((s) => s.mmi != null).map((s, i) => (
          <span key={s.key} title={`${s.name} ${s.mmi?.toFixed(1)}`}
            className={`absolute -translate-x-1/2 border border-ink ${s.plants.length ? "h-3 w-3 bg-action" : "h-2.5 w-2.5 rounded-full bg-ink"}`}
            style={{ left: pos(s.mmi!), bottom: `${4 + (i % 4) * 9}px` }} />
        ))}
      </div>
      <div className="flex h-3">
        {[4, 5, 6, 7, 8, 9].map((m) => <div key={m} className="flex-1" style={{ background: mmiColor(m) }} />)}
      </div>
      <div className="relative h-8 text-[11px] text-muted">
        {[4, 5, 6, 7, 8, 9, 10].map((m) => (
          <span key={m} className="num absolute -translate-x-1/2 text-ink" style={{ left: pos(m) }}>{roman(m)}</span>
        ))}
        {thresholds.map((t) => (
          <span key={t.m} className="absolute top-4 hidden -translate-x-1/2 whitespace-nowrap sm:inline" style={{ left: pos(t.m) }}>{t.t}</span>
        ))}
      </div>
      <figcaption className="sr-only">各受影響廠區在修正麥卡利震度（MMI）上的位置</figcaption>
    </figure>
  );
}
