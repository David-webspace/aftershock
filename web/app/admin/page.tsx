import { Suspense } from "react";
import { TopBar } from "@/components/TopBar";
import { apiGet } from "@/lib/api";

type Row = { ts: string; username: string | null; event: string; incident_id: number | null; detail: Record<string, unknown> | null };
const EVENT: Record<string, string> = {
  incident_open: "開應變案", inquiry_sent: "寄出詢問", follow_up_sent: "寄出追問", expedite_sent: "寄出追加請求", transfer_sent: "寄出調撥通知",
  qualify_sent: "寄出認證通知", draft_edit: "修改草稿", draft_rejected: "退回草稿", status_confirmed: "人工確認現況", clock_advance: "推進時鐘",
  plan_chosen: "選定方案", login_failed: "登入失敗",
};

async function Audit() {
  const rows = await apiGet<Row[]>("/api/admin/audit");
  return (
    <div className="overflow-x-auto border border-rule bg-sheet">
      <table className="w-full min-w-[44rem] text-sm">
        <thead className="bg-paper text-left text-xs text-muted">
          <tr>{["時間", "帳號", "事件", "應變案", "內容"].map((h) => <th key={h} className="px-3 py-2 font-normal">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="num px-3 py-2 whitespace-nowrap text-muted">{new Date(r.ts).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}</td>
              <td className="px-3 py-2">{r.username ?? "—"}</td>
              <td className="px-3 py-2 whitespace-nowrap">{EVENT[r.event] ?? r.event}</td>
              <td className="num px-3 py-2">{r.incident_id ?? ""}</td>
              <td className="num max-w-md truncate px-3 py-2 text-xs text-muted" title={JSON.stringify(r.detail)}>{r.detail ? JSON.stringify(r.detail) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminPage() {
  return (
    <>
      <Suspense fallback={<div className="h-12 bg-ink" />}>
        <TopBar />
      </Suspense>
      <main className="mx-auto max-w-7xl px-4 py-8">
        <h1 className="text-xl font-semibold">稽核紀錄</h1>
        <p className="mt-1 mb-4 text-sm text-muted">系統管理員只看得到誰在什麼時候做了什麼，看不到供應商往來內容。</p>
        <Suspense fallback={<p className="text-muted">讀取中…</p>}>
          <Audit />
        </Suspense>
      </main>
    </>
  );
}
