export type Me = { username: string; name: string; role: "buyer" | "manager" | "sysadmin"; role_label: string; commodities: string[] };

export type Scenario = {
  key: string; label: string; note: string; magnitude: number; place: string; t0: string; max_mmi: number; usgs_url: string;
};

export type LiveEvent = {
  id: string; magnitude: number; place: string; time: number; depth_km: number; shakemap: boolean; url: string;
  nearest: { site: string; km: number }[];
};

export type IncidentRow = { id: number; scenario: string; label: string; status: string; sim_hours: number; created_at: string; created_by: string };

export type SiteImpact = {
  key: string; name: string; lat: number; lon: number; mmi: number | null; pga_g: number | null; level: string; level_label: string;
  suppliers: number; plants: string[];
};

export type Status = {
  id: number; supplier_id: string; supplier: string; commodity: string; site_key: string; site: string; lat: number; lon: number;
  level: string; mmi: number | null; state: string; operating: string; capacity_pct: number | null; resume_day: number | null;
  damage: string | null; confirmed_by: string | null;
};

export type Stockout = {
  plant: string; part_no: string; category: string; level: string; single_source: boolean; impacted_share_pct: number;
  cover_days: number; stockout_day: number; orders_at_risk: number; order_qty_at_risk: number;
};

export type Incident = {
  id: number; sim_hours: number; now: string; status: string;
  scenario: { key: string; label: string; magnitude: number; place: string; lat: number; lon: number; t0: string; max_mmi: number; usgs_url: string };
  sites: SiteImpact[]; statuses: Status[]; exposure: { checked: number; stockouts: Stockout[] }; model_ready: boolean;
};

export type Msg = {
  id: number; supplier_id: string | null; supplier: string | null; commodity: string | null; direction: "in" | "out"; kind: string;
  status: string; from_addr: string; to_addr: string; subject: string; body: string; language: string; sim_hour: number;
  approved_by: string | null; guard_issues: string[] | null; parse_note: string | null; plan_id: number | null;
  parsed: { sites: Record<string, { operating: string; resume_day: number | null; capacity_pct: number | null; evidence: string | null; issues: string[] }> } | null;
};

export type Action = {
  type: "extra_order" | "transfer" | "qualify_alternate"; supplier?: string; from?: string; plant?: string; mode?: string; qty: number;
  cost_usd: number; lots: { plant: string; order_day: number; arrive_day: number; qty: number }[];
};

export type Option = {
  key: "low_cost" | "balanced" | "min_shortage"; label: string; cost_usd: number; shortage_units: number; orders_at_risk: number;
  parts_short: string[]; gap_reasons: Record<string, string>; plans: { part_no: string; category: string; actions: Action[] }[];
};

export type Options = {
  horizon_days: number; parts: string[]; no_action: { orders_at_risk: number; stockouts: number }; options: Option[];
  explanation: { summary: string; source: string; note: string | null };
};
