"use client";

import { useState } from "react";
import type { Incident, Me, Msg } from "@/lib/types";
import { MailTab } from "./MailTab";
import { PlanTab } from "./PlanTab";
import { RiskTab } from "./RiskTab";
import { StatusTab } from "./StatusTab";

export function Workbench({ incident, messages, me }: { incident: Incident; messages: Msg[]; me: Me }) {
  const drafts = messages.filter((m) => m.status === "draft").length;
  const review = incident.statuses.filter((s) => s.state === "needs_review").length;
  const tabs = [
    { key: "status", label: "供應商現況", badge: review },
    { key: "mail", label: "信件", badge: drafts },
    { key: "risk", label: "斷料風險", badge: incident.exposure.stockouts.length },
    { key: "plan", label: "補救方案", badge: 0 },
  ] as const;
  const [tab, setTab] = useState<(typeof tabs)[number]["key"]>(drafts ? "mail" : "status");

  return (
    <section className="flex min-h-0 min-w-0 flex-col">
      <div role="tablist" aria-label="工作區" className="flex shrink-0 overflow-x-auto border-b border-rule bg-sheet">
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={`shrink-0 border-b-2 px-4 py-2.5 text-sm ${tab === t.key ? "border-action font-medium text-ink" : "border-transparent text-muted hover:text-ink"}`}>
            {t.label}
            {t.badge > 0 && <span className="num ml-1.5 rounded-sm bg-wait-wash px-1.5 text-xs text-wait">{t.badge}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === "status" && <StatusTab statuses={incident.statuses} me={me} />}
        {tab === "mail" && <MailTab messages={messages} />}
        {tab === "risk" && <RiskTab incident={incident} />}
        {tab === "plan" && <PlanTab incidentId={incident.id} me={me} chosen={incident.plan} />}
      </div>
    </section>
  );
}
