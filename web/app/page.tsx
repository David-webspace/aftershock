import Link from "next/link";
import { Suspense } from "react";
import { OpenButton } from "@/components/OpenButton";
import { TopBar } from "@/components/TopBar";
import { apiGet } from "@/lib/api";
import { mmiColor, tPlus } from "@/lib/mmi";
import type { IncidentRow, LiveEvent, Scenario } from "@/lib/types";

const fmt = (iso: string | number) => new Date(iso).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false });

async function Incidents() {
  const rows = await apiGet<IncidentRow[]>("/api/incidents");
  if (!rows.length) return <p className="text-sm text-muted">還沒有應變案。從下方選一起真實地震重播，或從即時地震開案。</p>;
  return (
    <ul className="divide-y divide-rule border-y border-rule bg-sheet">
      {rows.map((r) => (
        <li key={r.id}>
          <Link href={`/incidents/${r.id}`} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-3 py-3 hover:bg-action-wash">
            <span className="num text-sm text-muted">#{r.id}</span>
            <span className="min-w-0 flex-1 font-medium break-words">{r.label}</span>
            <span className="num text-sm">{tPlus(r.sim_hours)}</span>
            <span className="text-xs text-muted">{r.source === "auto" ? "自動偵測" : r.created_by}・{fmt(r.created_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

async function Scenarios() {
  const list = await apiGet<Scenario[]>("/api/scenarios");
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {list.map((s) => (
        <li key={s.key} className="flex flex-col rounded-sm border border-rule bg-sheet p-4">
          <div className="flex items-start gap-3">
            <span className="font-cond text-5xl leading-none font-semibold">M{s.magnitude}</span>
            <span className="ml-auto flex items-center gap-1.5 text-xs text-muted">
              最大震度
              <span className="num rounded-sm px-1.5 py-0.5 text-ink" style={{ background: mmiColor(s.max_mmi) }}>MMI {s.max_mmi.toFixed(1)}</span>
            </span>
          </div>
          <p className="mt-2 font-medium break-words">{s.label}</p>
          <p className="num text-xs text-muted">{fmt(s.t0)}（台北）</p>
          <p className="mt-2 flex-1 text-sm break-words text-muted">{s.note}</p>
          <div className="mt-3 flex items-center justify-between gap-2">
            <a href={s.usgs_url} target="_blank" rel="noreferrer" className="text-xs text-action underline-offset-2 hover:underline">USGS 事件頁</a>
            <OpenButton scenario={s.key} label="重播" />
          </div>
        </li>
      ))}
    </ul>
  );
}

async function Live() {
  const { events, error, auto_detect_minutes: every } = await apiGet<{ events: LiveEvent[]; error: string | null; auto_detect_minutes: number }>("/api/live");
  const note = (
    <p className="mb-3 text-sm text-muted">
      USGS 最近 7 天規模 4.5 以上、距離我們的供應商或工廠 500 公里內的地震。有震度資料（ShakeMap）就能開案。
      {every > 0 ? `自動偵測已開啟：每 ${every} 分鐘檢查一次，供應商廠區達到「需要確認」就自動開案，並寄風險快報給負責的採購。`
        : "自動偵測未開啟（.env 的 AUTO_DETECT_MINUTES）。"}
    </p>
  );
  if (error) return <>{note}<p className="text-sm text-stop">{error}</p></>;
  if (!events.length) return <>{note}<p className="text-sm text-muted">最近 7 天沒有規模 4.5 以上的地震發生在供應商或工廠 500 公里內。</p></>;
  return (
    <>
    {note}
    <ul className="divide-y divide-rule border-y border-rule bg-sheet">
      {events.slice(0, 8).map((e) => (
        <li key={e.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-3">
          <span className="font-cond w-14 text-2xl font-semibold">M{e.magnitude.toFixed(1)}</span>
          <div className="min-w-0 flex-1">
            <p className="break-words">{e.place}</p>
            <p className="text-xs break-words text-muted">
              {fmt(e.time)}・深度 <span className="num">{Math.round(e.depth_km)}</span> km・最近：
              {e.nearest.map((n) => `${n.site} ${n.km} km`).join("、")}
            </p>
          </div>
          {e.incident_id ? <Link href={`/incidents/${e.incident_id}`} className="text-sm text-action underline-offset-2 hover:underline">已開案 #{e.incident_id}</Link>
            : e.shakemap ? <OpenButton scenario={`usgs:${e.id}`} /> : <span className="text-xs text-muted">尚無震度資料</span>}
        </li>
      ))}
    </ul>
    </>
  );
}

function Loading({ text }: { text: string }) {
  return <p className="text-sm text-muted">{text}</p>;
}

export default function Home() {
  return (
    <>
      <Suspense fallback={<div className="h-12 bg-ink" />}>
        <TopBar />
      </Suspense>
      <main className="mx-auto max-w-7xl space-y-10 px-4 py-8">
        <section>
          <h1 className="mb-3 text-xl font-semibold">應變案</h1>
          <Suspense fallback={<Loading text="讀取中…" />}>
            <Incidents />
          </Suspense>
        </section>
        <section>
          <h2 className="text-xl font-semibold">重播真實地震</h2>
          <p className="mb-3 text-sm text-muted">以發震當下為起點重播；震度、工業區位置、匯率為真實資料，供應商與採購資料為合成。</p>
          <Suspense fallback={<Loading text="讀取中…" />}>
            <Scenarios />
          </Suspense>
        </section>
        <section>
          <h2 className="mb-1 text-xl font-semibold">即時地震</h2>
          <Suspense fallback={<Loading text="向 USGS 讀取中…" />}>
            <Live />
          </Suspense>
        </section>
      </main>
    </>
  );
}
