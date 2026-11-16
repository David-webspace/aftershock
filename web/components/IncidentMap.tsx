"use client";

import type { FeatureCollection } from "geojson";
import { useEffect, useMemo, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { LEVEL_LABEL, OPERATING, STATE } from "@/lib/mmi";
import type { Incident } from "@/lib/types";

const TONE = { ok: "#2c7a50", wait: "#b97c0c", stop: "#b8322a", idle: "#0f1a24" };
const EPICENTER = L.divIcon({ className: "", html: '<div style="font-size:22px;line-height:22px;color:#b8322a">✱</div>', iconSize: [22, 22], iconAnchor: [11, 11] });

function Fit({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.25), { maxZoom: 8 });
  }, [map, points]);
  return null;
}

export default function IncidentMap({ incident }: { incident: Incident }) {
  const [contours, setContours] = useState<FeatureCollection | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`/api/incidents/${incident.id}/contours`).then((r) => (r.ok ? r.json() : null)).then((d) => alive && setContours(d)).catch(() => null);
    return () => {
      alive = false;
    };
  }, [incident.id]);

  // 一個廠區可能有好幾家供應商：顏色取最需要注意的狀態
  const bySite = useMemo(() => {
    const order = { stop: 3, wait: 2, idle: 1, ok: 0 };
    const out = new Map<string, { tone: keyof typeof TONE; lines: string[] }>();
    for (const s of incident.statuses) {
      const st = STATE[s.state] ?? STATE.pending;
      const tone = s.operating === "stopped" ? "stop" : st.tone;
      const cur = out.get(s.site_key) ?? { tone: "ok" as const, lines: [] };
      if (order[tone] > order[cur.tone] || !cur.lines.length) cur.tone = tone;
      cur.lines.push(`${s.supplier}：${st.label}${s.operating !== "unknown" ? `・${OPERATING[s.operating]}` : ""}`);
      out.set(s.site_key, cur);
    }
    return out;
  }, [incident.statuses]);

  const points = useMemo<[number, number][]>(
    () => [[incident.scenario.lat, incident.scenario.lon], ...incident.sites.map((s) => [s.lat, s.lon] as [number, number])],
    [incident],
  );

  return (
    // 手機上單指拖曳留給頁面捲動，地圖用 +／− 與雙指縮放
    <MapContainer center={[incident.scenario.lat, incident.scenario.lon]} zoom={6} scrollWheelZoom={!L.Browser.mobile}
      dragging={!L.Browser.mobile} className="h-full w-full">
      {/* 不需要金鑰的淺灰底圖，讓震度等值線與廠區標記成為畫面主角 */}
      <TileLayer attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors; 震度：USGS ShakeMap" maxZoom={16}
        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}" />
      {contours && (
        <GeoJSON data={contours} style={(f) => ({ color: f?.properties?.color ?? "#999", weight: Number.isInteger(f?.properties?.value) ? 2 : 1, opacity: 0.9 })}>
        </GeoJSON>
      )}
      <TileLayer maxZoom={16} url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}" />
      <Marker position={[incident.scenario.lat, incident.scenario.lon]} icon={EPICENTER}>
        <Tooltip>震央：M{incident.scenario.magnitude} {incident.scenario.place}</Tooltip>
      </Marker>
      {incident.sites.map((s) => {
        const info = bySite.get(s.key);
        const own = s.plants.length > 0;
        return (
          <CircleMarker key={s.key} center={[s.lat, s.lon]} radius={own ? 9 : 7}
            pathOptions={{ color: own ? "#0e5560" : "#0f1a24", weight: own ? 3 : 1.5, fillColor: TONE[info?.tone ?? "idle"], fillOpacity: 0.9 }}>
            <Tooltip>
              <strong>{s.name}</strong> MMI {s.mmi?.toFixed(1)}・{LEVEL_LABEL[s.level]}
              {own && <><br />自有工廠 {s.plants.join("、")}</>}
              {info?.lines.map((l) => <span key={l}><br />{l}</span>)}
            </Tooltip>
          </CircleMarker>
        );
      })}
      <Fit points={points} />
    </MapContainer>
  );
}
