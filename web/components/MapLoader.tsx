"use client";

import dynamic from "next/dynamic";
import type { Incident } from "@/lib/types";

// Leaflet 需要 window，只在瀏覽器載入
const IncidentMap = dynamic(() => import("./IncidentMap"), { ssr: false, loading: () => <div className="h-full w-full animate-pulse bg-rule/40" /> });

export function MapLoader({ incident }: { incident: Incident }) {
  return <IncidentMap incident={incident} />;
}
