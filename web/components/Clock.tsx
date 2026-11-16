"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// 事件時鐘：示範用。推進後，到期的供應商回信會寄達、被解析；超過 24 小時沒有可用回覆的會產生追問草稿
export function Clock({ incidentId }: { incidentId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function advance(hours: number) {
    setBusy(hours);
    setNote(null);
    const res = await fetch(`/api/incidents/${incidentId}/advance`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ hours }),
    }).catch(() => null);
    const body = res ? ((await res.json().catch(() => ({}))) as { delivered?: number; received?: number; followups?: number; detail?: string }) : {};
    setBusy(null);
    if (!res?.ok) return setNote(body.detail ?? "推進失敗");
    setNote(`收到 ${body.received ?? 0} 封回信${body.followups ? `，產生 ${body.followups} 封追問草稿` : ""}`);
    router.refresh();
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {[6, 24].map((h) => (
        <button key={h} onClick={() => advance(h)} disabled={busy !== null}
          className="num rounded-sm border border-white/40 px-2.5 py-1 text-sm hover:bg-white/10 disabled:opacity-50">
          {busy === h ? "推進中…" : `+${h}h`}
        </button>
      ))}
      {note && <span role="status" className="text-xs text-white/70">{note}</span>}
    </div>
  );
}
