import Link from "next/link";
import { Suspense } from "react";
import { Clock } from "@/components/Clock";
import { MapLoader } from "@/components/MapLoader";
import { MmiRuler } from "@/components/MmiRuler";
import { TopBar } from "@/components/TopBar";
import { Workbench } from "@/components/work/Workbench";
import { apiGet } from "@/lib/api";
import { tPlus } from "@/lib/mmi";
import type { Incident, Me, Msg } from "@/lib/types";

const fmt = (iso: string) => new Date(iso).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false });

async function Body({ params }: { params: PageProps<"/incidents/[id]">["params"] }) {
  const { id } = await params;
  const [incident, messages, me] = await Promise.all([
    apiGet<Incident>(`/api/incidents/${encodeURIComponent(id)}`),
    apiGet<Msg[]>(`/api/incidents/${encodeURIComponent(id)}/messages`),
    apiGet<Me>("/api/me"),
  ]);
  const sc = incident.scenario;
  return (
    <>
      <section className="bg-ink text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-end gap-x-8 gap-y-3 px-4 pt-4 pb-5">
          <div className="min-w-0">
            <Link href="/" className="text-xs text-white/60 hover:text-white">← 應變案</Link>
            <p className="font-cond text-6xl leading-none font-semibold">M{sc.magnitude}</p>
            <p className="mt-1 break-words">{sc.label}<span className="ml-2 text-sm text-white/60">{sc.place}</span></p>
            <p className="num text-xs text-white/60">發震 {fmt(sc.t0)}（台北）・<a href={sc.usgs_url} target="_blank" rel="noreferrer" className="underline">USGS</a></p>
          </div>
          <div className="ml-auto">
            <p className="text-xs text-white/60">事件時鐘</p>
            <p className="font-cond text-5xl leading-none font-semibold">{tPlus(incident.sim_hours)}</p>
            <p className="num mb-2 text-xs text-white/60">{fmt(incident.now)}</p>
            <Clock incidentId={incident.id} />
          </div>
        </div>
      </section>
      <section className="border-b border-rule bg-sheet">
        <div className="mx-auto max-w-7xl px-4 pt-3">
          <p className="text-xs text-muted">
            受影響廠區 <span className="num text-ink">{incident.sites.length}</span>・依 USGS ShakeMap 實際震度
            {!incident.model_ready && <span className="ml-2 text-wait">尚未設定模型：回信需人工判讀</span>}
          </p>
          <MmiRuler sites={incident.sites} />
        </div>
      </section>
      <div className="mx-auto grid max-w-7xl gap-0 lg:h-[calc(100dvh-15rem)] lg:min-h-[36rem] lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="h-[45vh] min-h-72 border-rule lg:h-full lg:border-r">
          <MapLoader incident={incident} />
        </div>
        <Workbench incident={incident} messages={messages} me={me} />
      </div>
    </>
  );
}

export default function IncidentPage({ params }: PageProps<"/incidents/[id]">) {
  return (
    <>
      <Suspense fallback={<div className="h-12 bg-ink" />}>
        <TopBar />
      </Suspense>
      <Suspense fallback={<p className="mx-auto max-w-7xl px-4 py-8 text-muted">計算影響中…</p>}>
        <Body params={params} />
      </Suspense>
    </>
  );
}
