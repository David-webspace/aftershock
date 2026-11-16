import type { Incident } from "@/lib/types";

const day = (t0: string, d: number) => {
  const x = new Date(t0);
  x.setDate(x.getDate() + d);
  return x.toLocaleDateString("zh-TW", { timeZone: "Asia/Taipei", month: "numeric", day: "numeric" });
};

export function RiskTab({ incident }: { incident: Incident }) {
  const rows = incident.exposure.stockouts;
  return (
    <div>
      <p className="mb-3 text-sm text-muted break-words">
        檢查了 <span className="num">{incident.exposure.checked}</span> 筆「工廠 × 料件」；下列為地震造成、未來 60 天內會斷料的項目。
        已回覆或人工確認的供應商，以實際恢復日取代規劃假設。
      </p>
      {rows.length === 0 ? <p className="text-sm text-ok">目前推估不會因這起地震斷料。</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>{["斷料日", "工廠", "料號", "受影響來源", "可撐", "影響訂單"].map((h) => <th key={h} className="px-2 py-1.5 font-normal">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {rows.map((r) => (
                <tr key={`${r.plant}-${r.part_no}`}>
                  <td className="num px-2 py-2 text-stop">{day(incident.scenario.t0, r.stockout_day)}<span className="text-xs text-muted">（第 {r.stockout_day} 天）</span></td>
                  <td className="num px-2 py-2">{r.plant}</td>
                  <td className="px-2 py-2"><span className="num">{r.part_no}</span><span className="block text-xs text-muted">{r.category}</span></td>
                  <td className="px-2 py-2">{r.single_source ? <span className="text-stop">單一來源</span> : <span className="num">{r.impacted_share_pct}%</span>}</td>
                  <td className="num px-2 py-2">{r.cover_days} 天</td>
                  <td className="num px-2 py-2">{r.orders_at_risk} 張<span className="block text-xs text-muted">{r.order_qty_at_risk.toLocaleString()} 台</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
