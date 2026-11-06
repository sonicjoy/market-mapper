/** Pure helpers for the Venue gaps tree: sort / filter, node selection, Why sampling. */

import type {
  VenueGapFixture,
  VenueGapFixtureDetail,
  VenueGapLeague,
  VenueGapLegRow,
  VenueGapMarket,
  VenueGapSelection,
} from "../venueGapsApi";
import type { VenueGapSort } from "./venueGapsQuery";

/** Selections sent to the server per Why: one per contract type is enough for a market rule. */
export const MAX_SAMPLE_ROWS = 12;
const MARKET_SAMPLE_ROWS = 3;

export type VenueGapNode =
  | { kind: "league"; meta: string }
  | { kind: "fixture"; meta: string; fixtureKey: string }
  | { kind: "market"; meta: string; fixtureKey: string; marketId: string }
  | { kind: "selection"; meta: string; fixtureKey: string; marketId: string; key: string };

export type Coverage = "mapped" | "partial" | "unmapped";

type Counted = { total: number; mapped: number; unmapped: number; demand: number };

export function coverageOf(node: { total: number; mapped: number }): Coverage {
  if (node.total > 0 && node.mapped >= node.total) return "mapped";
  if (node.mapped > 0) return "partial";
  return "unmapped";
}

export function mappedPct(node: { total: number; mapped: number }): number {
  return node.total ? Math.round((node.mapped / node.total) * 100) : 0;
}

function compare(sort: VenueGapSort, a: Counted & { start?: string | null }, b: typeof a): number {
  if (sort === "demand") return b.demand - a.demand || b.unmapped - a.unmapped;
  if (sort === "start") return (a.start ?? "￿").localeCompare(b.start ?? "￿");
  return b.unmapped - a.unmapped || b.demand - a.demand;
}

function earliest(fixtures: VenueGapFixture[]): string | null {
  const starts = fixtures.map((fx) => fx.start_date).filter((s): s is string => Boolean(s));
  return starts.length ? starts.sort()[0] : null;
}

function matches(needle: string, league: VenueGapLeague, fixture: VenueGapFixture): boolean {
  if (!needle) return true;
  const hay = [league.meta_league, league.tip.league, league.tip.league_label, fixture.name, fixture.fixture_key]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(needle);
}

/** Leagues and their fixtures in display order; unmapped-only hides fully mapped branches. */
export function arrangeLeagues(
  leagues: VenueGapLeague[],
  { sort, unmappedOnly, q = "" }: { sort: VenueGapSort; unmappedOnly: boolean; q?: string },
): VenueGapLeague[] {
  const needle = q.trim().toLowerCase();
  const kept = leagues
    .map((league) => ({
      ...league,
      fixtures: league.fixtures
        .filter((fx) => (!unmappedOnly || fx.unmapped > 0) && matches(needle, league, fx))
        .map((fx) => ({ ...fx, start: fx.start_date }))
        .sort((a, b) => compare(sort, a, b)),
    }))
    .filter((league) => league.fixtures.length > 0);
  return kept
    .map((league) => ({ league, start: earliest(league.fixtures) }))
    .sort((a, b) => compare(sort, { ...a.league, start: a.start }, { ...b.league, start: b.start }))
    .map(({ league }) => league);
}

/** Keep only the picked market names (contract_type, case-insensitive); none picked keeps all. */
export function pickMarkets(markets: VenueGapMarket[], picked: readonly string[] = []): VenueGapMarket[] {
  if (!picked.length) return markets;
  const want = new Set(picked.map((name) => name.trim().toLowerCase()));
  return markets.filter((m) => want.has(m.contract_type.trim().toLowerCase()));
}

export function arrangeMarkets(
  markets: VenueGapMarket[],
  unmappedOnly: boolean,
  picked: readonly string[] = [],
): VenueGapMarket[] {
  return pickMarkets(markets, picked)
    .filter((m) => !unmappedOnly || m.unmapped > 0)
    .sort((a, b) => b.unmapped - a.unmapped || a.label.localeCompare(b.label));
}

export function arrangeSelections(selections: VenueGapSelection[], unmappedOnly: boolean): VenueGapSelection[] {
  return selections.filter((s) => !unmappedOnly || !s.mapped);
}

export function nodeId(node: VenueGapNode): string {
  switch (node.kind) {
    case "league":
      return `league:${node.meta}`;
    case "fixture":
      return `fixture:${node.fixtureKey}`;
    case "market":
      return `market:${node.fixtureKey}:${node.marketId}`;
    case "selection":
      return `selection:${node.key}`;
    default: {
      const _exhaustive: never = node;
      return _exhaustive;
    }
  }
}

function legRow(detail: VenueGapFixtureDetail, market: VenueGapMarket, sel: VenueGapSelection): VenueGapLegRow {
  return {
    key: sel.key,
    description: sel.outcome,
    league: detail.league ?? null,
    fixture: detail.name ?? null,
    sport: detail.sport ?? null,
    contract_type: market.contract_type,
    market_group: market.market_group,
  };
}

function firstUnmapped(market: VenueGapMarket, n: number): VenueGapSelection[] {
  return market.selections.filter((s) => !s.mapped).slice(0, n);
}

/** Unmapped selections under a fixture / market / selection node for the server to draft from. */
export function sampleRows(
  node: VenueGapNode,
  detail: VenueGapFixtureDetail | undefined,
  picked: readonly string[] = [],
): VenueGapLegRow[] {
  if (!detail || node.kind === "league") return [];
  if (node.kind === "fixture" && picked.length) {
    detail = { ...detail, markets: pickMarkets(detail.markets, picked) };
  }
  if (node.kind === "selection" || node.kind === "market") {
    const market = detail.markets.find((m) => m.market_id === node.marketId);
    if (!market) return [];
    const picked =
      node.kind === "selection"
        ? market.selections.filter((s) => s.key === node.key && !s.mapped)
        : firstUnmapped(market, MARKET_SAMPLE_ROWS);
    return picked.map((sel) => legRow(detail, market, sel));
  }
  const seen = new Set<string>();
  const rows: VenueGapLegRow[] = [];
  for (const market of [...detail.markets].sort((a, b) => b.unmapped - a.unmapped)) {
    const shape = `${market.market_group}|${market.contract_type}`;
    const [sel] = firstUnmapped(market, 1);
    if (!sel || seen.has(shape)) continue;
    seen.add(shape);
    rows.push(legRow(detail, market, sel));
    if (rows.length >= MAX_SAMPLE_ROWS) break;
  }
  return rows;
}
