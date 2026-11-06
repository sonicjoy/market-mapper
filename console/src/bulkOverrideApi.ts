/** Bulk override (mmmapper#21): event legs -> Optic fixture/market -> drafted pairs -> one batch. */

import { api } from "./api";

export type BulkLeg = {
  source_market_id: string;
  source_selection_id: string;
  name: string;
  line: number | null;
  demand: number;
};

export type BulkLegsResponse = {
  sportsbook: string;
  event: string;
  league: string | null;
  sport: string | null;
  player: boolean;
  day: string;
  legs: BulkLeg[];
  block_reason: string | null;
};

export type OpticFixture = {
  game_id: string;
  home: string;
  away: string;
  start_date: string;
  league: string;
};

export type OpticSelection = {
  game_id: string;
  market_id: string;
  market: string;
  selection: string;
  selection_line: string;
  points: number;
  selection_points: number;
  grouping_key: string;
  books?: number;
};

export type OpticMarket = { market_id: string; market: string; selections: OpticSelection[] };

export type PairStatus = "confident" | "review" | "ambiguous" | "no_match";

export type DraftPair = {
  source_market_id: string;
  source_selection_id: string;
  leg_name: string;
  status: PairStatus;
  reason: string;
  target: OpticSelection | null;
  alternatives: OpticSelection[];
};

export type DraftResponse = { pairs: DraftPair[]; counts: Record<PairStatus, number> };

export type BulkJob = {
  job_id: string;
  status: string;
  message: string;
  source_market_id: string;
  source_selection_id: string;
};

export type BulkBatch = {
  batch_id: string;
  sportsbook: string;
  operator: string;
  reason: string;
  jobs: BulkJob[];
  counts: Record<string, number>;
};

export const TERMINAL_JOB_STATUSES = new Set(["materialised", "accepted_not_materialised", "failed"]);

export const getBulkLegs = (event: string, sportsbook = "kalshi") =>
  api<BulkLegsResponse>(
    `/console/bulk-override/legs?${new URLSearchParams({ event, sportsbook }).toString()}`,
  );

export const searchOpticFixtures = (q: string, day: string) =>
  api<{ fixtures: OpticFixture[] }>(
    `/console/bulk-override/optic-fixtures?${new URLSearchParams({ q, day }).toString()}`,
  );

export const getOpticMarkets = (gameId: string) =>
  api<{ game_id: string; markets: OpticMarket[] }>(
    `/console/bulk-override/optic-markets?${new URLSearchParams({ game_id: gameId }).toString()}`,
  );

export const draftBulkOverride = (body: {
  sportsbook: string;
  league: string | null;
  game_id: string;
  market_id: string;
  no_market_id?: string;
  legs: BulkLeg[];
}) => api<DraftResponse>("/console/bulk-override/draft", { method: "POST", body: JSON.stringify(body) });

export type ConfirmedPair = {
  source_market_id: string;
  source_selection_id: string;
  game_id: string;
  market_id: string;
  selection: string;
  selection_line: string;
  points: number;
  selection_points: number;
  grouping_key: string;
};

export const publishBulkOverride = (body: { sportsbook: string; reason: string; pairs: ConfirmedPair[] }) =>
  api<BulkBatch>("/console/bulk-override/publish", { method: "POST", body: JSON.stringify(body) });

export const getBulkBatch = (batchId: string) =>
  api<BulkBatch>(`/console/bulk-override/batches/${encodeURIComponent(batchId)}`);

/** Stable key for an Optic selection (dropdown value). */
export function selectionKey(sel: OpticSelection): string {
  return [sel.market_id, sel.selection, sel.selection_line, sel.points, sel.grouping_key].join("|");
}

/** Human label for an Optic selection. */
export function selectionLabel(sel: OpticSelection): string {
  const name = sel.selection || sel.selection_line || "(no name)";
  const line = sel.points ? ` ${sel.points > 0 ? "+" : ""}${sel.points}` : "";
  const side = sel.selection && sel.selection_line ? ` ${sel.selection_line}` : "";
  return `${name}${side}${line}`;
}

/** The request row for one confirmed pair. */
export function confirmedPair(pair: DraftPair, target: OpticSelection): ConfirmedPair {
  return {
    source_market_id: pair.source_market_id,
    source_selection_id: pair.source_selection_id,
    game_id: target.game_id,
    market_id: target.market_id,
    selection: target.selection,
    selection_line: target.selection_line,
    points: Number(target.points) || 0,
    selection_points: Number(target.selection_points) || 0,
    grouping_key: target.grouping_key || "default",
  };
}
