/** Explore → Venue gaps: venue catalogue vs published market_mapping. */

import { api } from "./api";
import type { CartItemKind } from "./cartStore";
import type { EntryLocationState, MappableItem, UnmappedWhyReason } from "./types";

export type VenueGapTipStatus = "in_tip" | "disabled" | "not_in_tip";

export type VenueGapLeagueTip = {
  status: VenueGapTipStatus;
  league: string | null;
  league_label: string | null;
  sport: string | null;
  candidates: string[];
  fix: { action: "amend" | "create"; entry_state: EntryLocationState } | null;
};

type Counts = {
  total: number;
  mapped: number;
  unmapped: number;
  demand: number;
};

export type VenueGapFixture = Counts & {
  fixture_key: string;
  name: string;
  start_date: string | null;
  ttko_hours: number | null;
};

export type VenueGapLeague = Counts & {
  meta_league: string;
  sport_grouping: string | null;
  tip: VenueGapLeagueTip;
  fixtures: VenueGapFixture[];
};

export type VenueGapTotals = {
  selections: number;
  mapped: number;
  leagues: number;
  leagues_not_in_tip: number;
  fixtures: number;
  fixtures_unmapped: number;
};

/** One market name (contract_type) across the filtered fixtures, biggest unmapped first. */
export type VenueGapMarketOption = {
  name: string;
  total: number;
  unmapped: number;
  fixtures: number;
};

export type VenueGapsResponse = {
  platform: string;
  leagues: VenueGapLeague[];
  totals: VenueGapTotals;
  market_options?: VenueGapMarketOption[];
  error: string | null;
};

export type VenueGapSelection = {
  key: string;
  outcome: string;
  participant: string | null;
  mapped: boolean;
  demand: number;
};

export type VenueGapMarket = Counts & {
  market_id: string;
  market_group: string;
  contract_type: string;
  period_type: string | null;
  label: string;
  selections: VenueGapSelection[];
};

export type VenueGapFixtureDetail = {
  platform: string;
  fixture_key: string;
  name?: string;
  meta_league?: string | null;
  league?: string | null;
  sport?: string | null;
  markets: VenueGapMarket[];
  error: string | null;
};

/** One catalogue selection sent back so the server can draft its rules. */
export type VenueGapLegRow = {
  key: string;
  description: string;
  league: string | null;
  fixture: string | null;
  sport: string | null;
  contract_type: string;
  market_group: string;
};

export type VenueGapWhyItem = MappableItem & { sources: number };

export type VenueGapWhy = {
  mappable_items: VenueGapWhyItem[];
  has_fixes: boolean;
  reasons: UnmappedWhyReason[];
  sampled: number;
};

export type VenueGapStageResult = {
  ok: boolean;
  error?: string;
  cart_items: Array<{ kind: CartItemKind; label: string; payload: Record<string, unknown> }>;
  needs_editor: Array<{ label: string; entry_state: EntryLocationState }>;
  not_drafted?: string[];
};

export function listVenueGaps(opts: {
  platform: string;
  phase: string;
  q?: string;
  markets?: string[];
  kickoffFrom?: string;
  kickoffTo?: string;
  refresh?: boolean;
}) {
  const params = new URLSearchParams({ platform: opts.platform, phase: opts.phase });
  if (opts.q) params.set("q", opts.q);
  for (const value of opts.markets ?? []) params.append("market", value);
  if (opts.kickoffFrom) params.set("kickoff_from", opts.kickoffFrom);
  if (opts.kickoffTo) params.set("kickoff_to", opts.kickoffTo);
  if (opts.refresh) params.set("refresh", "true");
  return api<VenueGapsResponse>(`/console/venue-gaps?${params.toString()}`);
}

/** Fixture drill-down is shared by the table and the fix panel; the server memoises for 5 min too. */
export const FIXTURE_STALE_MS = 5 * 60 * 1000;

export function fixtureQueryKey(platform: string, fixtureKey: string) {
  return ["venue-gaps", "fixture", platform, fixtureKey] as const;
}

export function getVenueGapFixture(platform: string, fixtureKey: string) {
  const params = new URLSearchParams({ platform, fixture_key: fixtureKey });
  return api<VenueGapFixtureDetail>(`/console/venue-gaps/fixture?${params.toString()}`);
}

export function getVenueGapWhy(platform: string, rows: VenueGapLegRow[]) {
  return api<VenueGapWhy>("/console/venue-gaps/why", {
    method: "POST",
    body: JSON.stringify({ platform, rows }),
  });
}

export function stageVenueGap(platform: string, rows: VenueGapLegRow[], itemIds: string[]) {
  return api<VenueGapStageResult>("/console/venue-gaps/stage", {
    method: "POST",
    body: JSON.stringify({ platform, rows, item_ids: itemIds }),
  });
}
