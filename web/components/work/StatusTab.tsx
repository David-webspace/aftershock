"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { COMMODITY, OPERATING, STATE, mmiColor } from "@/lib/mmi";
import type { Me, Status } from "@/lib/types";
import { post } from "./post";

const TONE = { ok: "text-ok", wait: "text-wait", stop: "text-stop", idle: "text-muted" };

export function StatusTab({ statuses, me }: { statuses: Status[]; me: Me }) {
  if (!statuses.length) return <p className="text-sm text-muted">沒有{me.role === "buyer" ? "你負責料件類別的" : ""}受影響供應商。</p>;
  return (
    <ul className="space-y-2">
      {statuses.map((s) => <StatusRow key={s.id} s={s} />)}
    </ul>
  );
}

function StatusRow({ s }: { s: Status }) {
  const st = STATE[s.state] ?? STATE.pending;
  const [editing, setEditing] = useState(false);
  return (
    <li className="rounded-sm border border-rule bg-sheet p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {/* 顯示數值而非羅馬數字：7.6 四捨五入是 VIII，但影響等級依「7 以上」判定，直接顯示數值才不會對不上 */}
        <span className="num rounded-sm px-1.5 py-0.5 text-xs" style={{ background: mmiColor(s.mmi) }} title="修正麥卡利震度（MMI）">
          MMI {s.mmi?.toFixed(1) ?? "—"}
        </span>
        <span className="min-w-0 flex-1 font-medium break-words">{s.supplier}</span>
        <span className={`text-sm ${TONE[st.tone]}`}>{st.label}</span>
      </div>
      <p className="mt-1 text-xs break-words text-muted">{s.site}・{COMMODITY[s.commodity] ?? s.commodity}</p>
      {s.operating !== "unknown" && (
        <p className="mt-1.5 text-sm break-words">
          {OPERATING[s.operating]}
          {s.operating === "partial" && s.capacity_pct != null && <>，產能約 <span className="num">{s.capacity_pct}%</span></>}
          {s.operating !== "normal" && s.resume_day != null && <>，預計第 <span className="num">{s.resume_day}</span> 天恢復</>}
          {s.confirmed_by && <span className="text-muted">（{s.confirmed_by} 確認）</span>}
        </p>
      )}
      {(s.state === "needs_review" || s.state === "no_reply") && !editing && (
        <button onClick={() => setEditing(true)} className="mt-2 text-sm text-action underline-offset-2 hover:underline">人工確認現況</button>
      )}
      {editing && <ConfirmForm s={s} done={() => setEditing(false)} />}
    </li>
  );
}

function ConfirmForm({ s, done }: { s: Status; done: () => void }) {
  const router = useRouter();
  const [operating, setOperating] = useState(s.operating === "unknown" ? "stopped" : s.operating);
  const [cap, setCap] = useState(String(s.capacity_pct ?? 50));
  const [day, setDay] = useState(String(s.resume_day ?? 14));
  const [error, setError] = useState<string | null>(null);
  const field = "rounded-sm border border-rule bg-white px-2 py-1 text-sm focus:border-action focus:outline-none";

  async function save() {
    const err = await post(`/api/status/${s.id}/confirm`, {
      operating, capacity_pct: operating === "partial" ? Number(cap) : null, resume_day: operating === "normal" ? null : Number(day),
    });
    if (err) return setError(err);
    done();
    router.refresh();
  }

  return (
    <div className="mt-2 flex flex-wrap items-end gap-2 border-t border-rule pt-2">
      <label className="text-xs text-muted">狀態
        <select value={operating} onChange={(e) => setOperating(e.target.value)} className={`${field} mt-0.5 block`}>
          <option value="normal">正常</option><option value="partial">部分運作</option><option value="stopped">停工</option>
        </select>
      </label>
      {operating === "partial" && (
        <label className="text-xs text-muted">產能 %
          <input inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value)} className={`${field} num mt-0.5 block w-20`} />
        </label>
      )}
      {operating !== "normal" && (
        <label className="text-xs text-muted">第幾天恢復
          <input inputMode="numeric" value={day} onChange={(e) => setDay(e.target.value)} className={`${field} num mt-0.5 block w-20`} />
        </label>
      )}
      <button onClick={save} className="rounded-sm bg-action px-3 py-1.5 text-sm text-white hover:bg-action-deep">確認</button>
      <button onClick={done} className="px-2 py-1.5 text-sm text-muted">取消</button>
      {error && <p role="alert" className="w-full text-xs text-stop">{error}</p>}
    </div>
  );
}
