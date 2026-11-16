"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Action, Me, Options } from "@/lib/types";
import { post } from "./post";

const MODE: Record<string, string> = { sea: "海運", air: "空運", truck: "陸運" };

function describe(a: Action): string {
  if (a.type === "extra_order") return `向 ${a.supplier} 追加 ${a.qty.toLocaleString()} 個 → ${a.plant}（${MODE[a.mode ?? ""] ?? a.mode}）`;
  if (a.type === "transfer") return `${a.from} 調撥 ${a.qty.toLocaleString()} 個 → ${a.plant}`;
  return `啟用備援來源 ${a.supplier}，認證後採購 ${a.qty.toLocaleString()} 個`;
}

export function PlanTab({ incidentId, me }: { incidentId: number; me: Me; t0: string }) {
  const router = useRouter();
  const [data, setData] = useState<Options | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/incidents/${incidentId}/options`).catch(() => null);
    setBusy(false);
    if (!res?.ok) return setError("計算失敗，請稍後再試");
    setData((await res.json()) as Options);
  }

  async function choose(profile: string, label: string) {
    setBusy(true);
    const err = await post(`/api/incidents/${incidentId}/plan`, { profile });
    setBusy(false);
    if (err) return setError(err);
    setDone(`已選定「${label}」，追加出貨請求與內部通知已產生草稿，請到「信件」分頁核准。`);
    router.refresh();
  }

  if (!data) {
    return (
      <div>
        <p className="mb-3 text-sm break-words text-muted">
          以目前的供應商狀況（已回覆或人工確認的以實際恢復日計算）求解：追加訂單、空運、工廠間調撥、啟用備援來源與接受缺料之間的取捨。
        </p>
        <button onClick={load} disabled={busy} className="rounded-sm bg-action px-3 py-1.5 text-sm text-white hover:bg-action-deep disabled:opacity-50">
          {busy ? "求解中…" : "計算三個方案"}
        </button>
        {error && <p role="alert" className="mt-2 text-sm text-stop">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm">
        不採取行動：<span className="num">{data.no_action.stockouts}</span> 筆斷料，影響客戶訂單 <span className="num">{data.no_action.orders_at_risk}</span> 張
      </p>
      <div className="space-y-3">
        {data.options.map((o) => (
          <article key={o.key} className="rounded-sm border border-rule bg-sheet p-3">
            <div className="flex items-center gap-3">
              <h3 className="font-medium">{o.label}</h3>
              {me.role === "manager" && (
                <button onClick={() => choose(o.key, o.label)} disabled={busy || !!done}
                  className="ml-auto rounded-sm border border-action px-3 py-1 text-sm text-action hover:bg-action-wash disabled:opacity-40">選定此方案</button>
              )}
            </div>
            <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
              <div><dt className="text-xs text-muted">額外成本</dt><dd className="num">US${o.cost_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}</dd></div>
              <div><dt className="text-xs text-muted">剩餘缺料</dt><dd className={`num ${o.shortage_units ? "text-stop" : "text-ok"}`}>{o.shortage_units.toLocaleString()} 個</dd></div>
              <div><dt className="text-xs text-muted">影響訂單</dt><dd className="num">{o.orders_at_risk} 張</dd></div>
            </dl>
            <ul className="mt-2 space-y-0.5 border-t border-rule pt-2 text-xs break-words text-muted">
              {o.plans.flatMap((p) => p.actions.map((a, i) => <li key={`${p.part_no}-${i}`}><span className="num text-ink">{p.part_no}</span> {describe(a)}</li>))}
              {o.plans.every((p) => !p.actions.length) && <li>不需要額外動作</li>}
            </ul>
          </article>
        ))}
      </div>
      <section className="rounded-sm bg-paper p-3">
        <h3 className="mb-1 text-xs text-muted">比較說明（由程式依求解結果產生）</h3>
        <p className="text-sm break-words whitespace-pre-wrap">{data.explanation.summary}</p>
      </section>
      {me.role !== "manager" && <p className="text-xs text-muted">選定方案會產生對外承諾與內部調撥，由供應鏈主管決定。</p>}
      {done && <p role="status" className="text-sm text-ok">{done}</p>}
      {error && <p role="alert" className="text-sm text-stop">{error}</p>}
    </div>
  );
}
