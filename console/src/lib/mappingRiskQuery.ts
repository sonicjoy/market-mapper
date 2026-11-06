/** URL state for Mapping risk (platform, tier, signal, search, kickoff window, flagged, paging). */

import { DEFAULT_PAGE_SIZE, parseLimit, parsePage, type PageSize } from "./rulesQuery";

export const RISK_PLATFORMS = [
  { value: "", label: "All" },
  { value: "kalshi", label: "Kalshi" },
  { value: "polymarket", label: "Polymarket" },
  { value: "polymarket (usa)", label: "Polymarket (USA)" },
  { value: "novig", label: "Novig" },
  { value: "prophet x", label: "Prophet X" },
  { value: "sx bet", label: "SX Bet" },
  { value: "underdog", label: "Underdog" },
  { value: "crypto.com", label: "crypto.com" },
] as const;

export const RISK_TIERS = ["high", "medium", "low"] as const;

/** Operator labels for the scorer's signal codes (console_mismap_score.py). */
export const SIGNAL_LABELS: Record<string, string> = {
  optic_disagrees: "Optic disagrees",
  stale_game: "Rescheduled (stale game id)",
  missing_fixture_id: "No Optic fixture id",
  key_multi_market: "One venue id, several markets",
  ai_flagged: "AI validator",
  name_mismatch: "Name mismatch",
  price_gap: "Price gap",
  period_mismatch: "Period mismatch",
  shared_selection: "Shared selection",
};

export type MappingRiskQueryState = {
  platform: string;
  tier: string;
  reason: string;
  q: string;
  /** Kickoff window bounds, UTC wall time as `YYYY-MM-DDTHH:MM` (datetime-local shape). */
  kickoffFrom: string;
  kickoffTo: string;
  flagged: boolean;
  page: number;
  limit: PageSize;
};

export function readMappingRiskQuery(params: URLSearchParams): MappingRiskQueryState {
  const tier = params.get("tier") ?? "";
  return {
    platform: params.get("platform") ?? "",
    tier: (RISK_TIERS as readonly string[]).includes(tier) ? tier : "",
    reason: params.get("reason") ?? "",
    q: params.get("q") ?? "",
    kickoffFrom: params.get("from") ?? "",
    kickoffTo: params.get("to") ?? "",
    flagged: params.get("flagged") === "1",
    page: parsePage(params.get("page")),
    limit: parseLimit(params.get("limit")),
  };
}

export function writeMappingRiskQuery(
  current: URLSearchParams,
  patch: Partial<MappingRiskQueryState>,
): URLSearchParams {
  const next = { ...readMappingRiskQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.platform) params.set("platform", next.platform);
  if (next.tier) params.set("tier", next.tier);
  if (next.reason) params.set("reason", next.reason);
  if (next.q) params.set("q", next.q);
  if (next.kickoffFrom) params.set("from", next.kickoffFrom);
  if (next.kickoffTo) params.set("to", next.kickoffTo);
  if (next.flagged) params.set("flagged", "1");
  if (next.page > 0) params.set("page", String(next.page));
  if (next.limit !== DEFAULT_PAGE_SIZE) params.set("limit", String(next.limit));
  return params;
}

/** "Kalshi 74% vs fair 55%"-style probability pair for the price column; null when either side is missing. */
export function impliedPair(venue: number | null, fair: number | null): string | null {
  if (!venue || !fair || venue <= 1 || fair <= 1) return null;
  return `${Math.round(100 / venue)}% vs ${Math.round(100 / fair)}%`;
}
