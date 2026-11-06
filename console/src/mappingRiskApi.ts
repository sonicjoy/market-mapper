/** Explore -> Mapping risk: live mappings scored for mismapping risk (mmmapper#23). */

import { api } from "./api";

export type RiskTier = "high" | "medium" | "low";

export type RiskSignal = { code: string; tier: RiskTier; text: string };

export type MappingFlag = {
  work_item_id: string;
  status: "open" | "resolved";
  severity: string | null;
  note: string | null;
  flagged_by: string | null;
  resolved_by: string | null;
  resolution: string | null;
  created_at: string;
  updated_at: string;
};

export type MappingRiskRow = {
  sb: string;
  book: string | null;
  src_key: string;
  canon: string;
  src_market: string | null;
  src_selection: string | null;
  game_id: string | null;
  league: string | null;
  market_id: string | null;
  selection: string | null;
  selection_line: string | null;
  points: number | null;
  mapping_source: string | null;
  rank_class: string | null;
  is_rfq_winner: boolean | null;
  is_override: boolean | null;
  venue_price: number | null;
  fair_price: number | null;
  exchange_text: string | null;
  start_date: string | null;
  tier: RiskTier | null;
  signals: RiskSignal[];
  fingerprint: string;
  flag?: MappingFlag | null;
};

export type MappingRiskResponse = {
  rows: MappingRiskRow[];
  count: number;
  facets: {
    tiers: Partial<Record<RiskTier, number>>;
    reasons: Record<string, number>;
    platforms: Record<string, number>;
  };
  coverage: Array<{ platform: string; missing: string[] }>;
  /** When the server's cached BigQuery snapshot was taken (1h cache). */
  cached_at?: string | null;
  error: string | null;
};

export type MappingRiskFilters = {
  platform?: string;
  tier?: string;
  reason?: string;
  q?: string;
  kickoffFrom?: string;
  kickoffTo?: string;
  flagged?: boolean;
  limit?: number;
  offset?: number;
  refresh?: boolean;
};

export function listMappingRisk(opts: MappingRiskFilters) {
  const params = new URLSearchParams();
  if (opts.platform) params.set("platform", opts.platform);
  if (opts.tier) params.set("tier", opts.tier);
  if (opts.reason) params.set("reason", opts.reason);
  if (opts.q) params.set("q", opts.q);
  if (opts.kickoffFrom) params.set("kickoff_from", opts.kickoffFrom);
  if (opts.kickoffTo) params.set("kickoff_to", opts.kickoffTo);
  if (opts.flagged) params.set("flagged", "true");
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  if (opts.refresh) params.set("refresh", "true");
  const q = params.toString();
  return api<MappingRiskResponse>(`/console/mapping-risk${q ? `?${q}` : ""}`);
}

export function flagMapping(row: MappingRiskRow, note: string) {
  const { flag: _flag, ...snapshot } = row;
  return api<MappingFlag>("/console/mapping-risk/flag", {
    method: "POST",
    body: JSON.stringify({ row: snapshot, note }),
  });
}

export function resolveMappingFlag(fingerprint: string, note: string) {
  return api<MappingFlag>("/console/mapping-risk/resolve", {
    method: "POST",
    body: JSON.stringify({ fingerprint, note }),
  });
}
