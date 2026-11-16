"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { OPERATING } from "@/lib/mmi";
import type { Msg } from "@/lib/types";
import { post } from "./post";

const KIND: Record<string, string> = { inquiry: "詢問", follow_up: "追問", reply: "回信", expedite: "追加出貨請求", transfer: "內部調撥", qualify: "備援認證" };
const STATUS: Record<string, string> = {
  draft: "草稿・待核准", sent: "已寄出", rejected: "已退回", received: "已收到", parsed: "已解析採用", needs_review: "需人工確認",
};

export function MailTab({ messages }: { messages: Msg[] }) {
  const drafts = messages.filter((m) => m.status === "draft");
  const rest = messages.filter((m) => m.status !== "draft").reverse();
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 text-sm font-medium">待核准 <span className="num text-muted">{drafts.length}</span></h3>
        {drafts.length ? <ul className="space-y-2">{drafts.map((m) => <MailCard key={m.id} m={m} />)}</ul>
          : <p className="text-sm text-muted">沒有待核准的信。</p>}
      </section>
      <section>
        <h3 className="mb-2 text-sm font-medium">往來紀錄</h3>
        {rest.length ? <ul className="space-y-2">{rest.map((m) => <MailCard key={m.id} m={m} />)}</ul>
          : <p className="text-sm text-muted">還沒有寄出或收到的信。</p>}
      </section>
    </div>
  );
}

function MailCard({ m }: { m: Msg }) {
  const router = useRouter();
  const [open, setOpen] = useState(m.status === "draft" && !!m.guard_issues?.length);
  const [body, setBody] = useState(m.body);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const issues = m.guard_issues ?? [];
  const edited = body !== m.body;

  async function act(path: string, payload?: unknown, method?: string) {
    setBusy(true);
    setError(await post(path, payload, method));
    setBusy(false);
    router.refresh();
  }

  return (
    <li className={`rounded-sm border bg-sheet ${m.direction === "in" ? "border-l-4 border-rule border-l-action" : "border-rule"}`}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="w-full p-3 text-left">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span className="rounded-sm bg-paper px-1.5 py-0.5 text-ink">{KIND[m.kind] ?? m.kind}</span>
          <span>{STATUS[m.status] ?? m.status}</span>
          <span className="num ml-auto">T+{m.sim_hour}h</span>
        </div>
        <p className="mt-1 font-medium break-words">{m.supplier ?? "內部通知"}</p>
        <p className="text-sm break-words text-muted">{m.subject}</p>
      </button>
      {open && (
        <div className="border-t border-rule p-3">
          <p className="num mb-2 text-xs break-all text-muted">{m.direction === "in" ? `寄件人 ${m.from_addr}` : `收件人 ${m.to_addr}`}</p>
          {m.status === "draft" ? (
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={12} aria-label="信件內容"
              className="w-full rounded-sm border border-rule bg-white p-2 text-sm focus:border-action focus:outline-none" />
          ) : (
            <pre className="text-sm break-words whitespace-pre-wrap">{m.body}</pre>
          )}
          {issues.length > 0 && (
            <ul className="mt-2 space-y-1 rounded-sm bg-stop-wash p-2 text-sm text-stop">
              {issues.map((i) => <li key={i}>不能寄出：{i}</li>)}
            </ul>
          )}
          {m.direction === "in" && <Parsed m={m} />}
          {m.status === "draft" && (
            <div className="mt-3 flex flex-wrap gap-2">
              {edited && <button disabled={busy} onClick={() => act(`/api/messages/${m.id}`, { body }, "PATCH")}
                className="rounded-sm border border-action px-3 py-1.5 text-sm text-action">儲存修改並檢查</button>}
              <button disabled={busy || edited || issues.length > 0} onClick={() => act(`/api/messages/${m.id}/approve`)}
                className="rounded-sm bg-action px-3 py-1.5 text-sm text-white hover:bg-action-deep disabled:opacity-40">核准並寄出</button>
              <button disabled={busy} onClick={() => act(`/api/messages/${m.id}/reject`)} className="px-2 py-1.5 text-sm text-muted hover:text-stop">退回</button>
            </div>
          )}
          {error && <p role="alert" className="mt-2 text-sm text-stop">{error}</p>}
        </div>
      )}
    </li>
  );
}

function Parsed({ m }: { m: Msg }) {
  if (!m.parsed && !m.parse_note) return null;
  return (
    <div className="mt-3 rounded-sm bg-paper p-2 text-sm">
      <p className="mb-1 text-xs text-muted">模型整理結果（程式驗證後才採用）</p>
      {m.parsed && Object.entries(m.parsed.sites).map(([site, r]) => (
        <p key={site} className="break-words">
          <span className="num text-xs text-muted">{site}</span> {OPERATING[r.operating]}
          {r.resume_day != null && r.operating !== "normal" && <>，第 <span className="num">{r.resume_day}</span> 天恢復</>}
          {r.evidence && <span className="block text-xs text-muted">依據：「{r.evidence}」</span>}
        </p>
      ))}
      {m.parse_note && <p className="mt-1 text-xs break-words text-wait">{m.parse_note}</p>}
    </div>
  );
}
