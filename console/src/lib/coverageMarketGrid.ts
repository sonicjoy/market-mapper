import {
  CANONICAL_MARKET_TYPES,
  SPORTSBOOKS,
  sourceKeyTypeFor,
  sportsbookLabel,
} from "../entryEnums";
import type { CoveragePlatform, EntryLocationState, LeagueExchange, MarketRuleRow } from "../types";

/** Published market_mapping sportsbook name → console grid id. */
const PUBLISHED_SPORTSBOOK_ALIASES: Record<string, string> = {
  kalshi: "kalshi",
  "crypto.com": "crypto.com",
  optic: "optic",
  polymarket: "polymarket",
  "polymarket (usa)": "polymarket_usa",
  polymarket_usa: "polymarket_usa",
  px: "px",
  "prophet x": "px",
  prophetx: "px",
  novig: "novig",
  underdog: "underdog",
  dkex: "dkex",
  runshop: "runshop",
};

export type CoverageCellKey = string;

export type CoverageLeagueDetail = {
  sport: string;
  optic_league_id: string;
  fixture_source: string;
  fixture_horizon_hours: number;
  enabled: boolean;
  entity_type?: string;
  alias_enforcement?: string;
  runshop_enabled?: boolean;
  exchanges: LeagueExchange[];
};

export function normalizeCoverageSportsbook(sportsbook: string): string {
  const key = sportsbook.trim().toLowerCase();
  return PUBLISHED_SPORTSBOOK_ALIASES[key] ?? key;
}

function nonEmpty(...values: unknown[]): string {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) return text;
  }
  return "";
}

export function coverageCellKey(sportsbook: string, canonical: string): CoverageCellKey {
  return `${normalizeCoverageSportsbook(sportsbook)}::${canonical.trim()}`;
}

export function parseCoverageCellKey(key: CoverageCellKey): { sportsbook: string; canonical: string } {
  const split = key.indexOf("::");
  if (split < 0) return { sportsbook: key, canonical: "" };
  return { sportsbook: key.slice(0, split), canonical: key.slice(split + 2) };
}

export function ruleCanonical(row: MarketRuleRow): string {
  return (row.canonical_market_type ?? "").trim();
}

export function cellIsOn(rows: readonly MarketRuleRow[]): boolean {
  return rows.some(
    (row) => row.enabled !== false && row.action === "map" && Boolean(ruleCanonical(row)),
  );
}

export function rulesForCell(
  rules: readonly MarketRuleRow[],
  sportsbook: string,
  canonical: string,
): MarketRuleRow[] {
  const book = normalizeCoverageSportsbook(sportsbook);
  const market = canonical.trim();
  return rules.filter(
    (row) => normalizeCoverageSportsbook(row.sportsbook) === book && ruleCanonical(row) === market,
  );
}

export function cellHasRule(
  rules: readonly MarketRuleRow[],
  sportsbook: string,
  canonical: string,
): boolean {
  return rulesForCell(rules, sportsbook, canonical).length > 0;
}

export function cellSourceLabel(
  rules: readonly MarketRuleRow[],
  sportsbook: string,
  canonical: string,
): string {
  const keys = [
    ...new Set(
      rulesForCell(rules, sportsbook, canonical)
        .map((row) => row.source_key.trim())
        .filter(Boolean),
    ),
  ];
  return keys.join(" · ");
}

export function coveragePlatformLabel(sportsbook: string): string {
  return sportsbookLabel(normalizeCoverageSportsbook(sportsbook));
}

export function publishedMappedKeys(
  platforms: readonly CoveragePlatform[],
): Set<CoverageCellKey> {
  const out = new Set<CoverageCellKey>();
  for (const plat of platforms) {
    for (const mkt of plat.markets) {
      if (!mkt.mapped) continue;
      out.add(coverageCellKey(plat.sportsbook, mkt.canonical_market_type));
    }
  }
  return out;
}

export function missingMarketEntryState(opts: {
  league: string;
  sportsbook: string;
  canonical: string;
}): EntryLocationState {
  const sportsbook = opts.sportsbook.trim();
  const canonical = opts.canonical.trim();
  return {
    fromRules: true,
    mode: "amend",
    tab: "market",
    league: opts.league.trim(),
    sportsbook,
    action: "map",
    canonical_market_type: canonical || null,
    source_key_type: sourceKeyTypeFor(sportsbook),
    note: `From Coverage: add ${sportsbook} ${canonical}`.trim(),
  };
}

export function orderCoveragePlatforms(books: readonly string[]): string[] {
  const present = new Set(books.map((book) => normalizeCoverageSportsbook(book)).filter(Boolean));
  const out: string[] = [];
  const take = (book: string) => {
    if (!present.has(book)) return;
    out.push(book);
    present.delete(book);
  };
  take("optic");
  for (const book of SPORTSBOOKS) take(book);
  out.push(...[...present].sort((a, b) => a.localeCompare(b)));
  return out;
}

export function orderCoverageMarkets(
  types: readonly string[],
  outputOrder: readonly string[] = [],
): string[] {
  const present = new Set(types.filter(Boolean));
  const out: string[] = [];
  const take = (value: string) => {
    if (!present.has(value)) return;
    present.delete(value);
    out.push(value);
  };
  for (const value of outputOrder) take(value);
  for (const value of CANONICAL_MARKET_TYPES) take(value);
  out.push(...[...present].sort((a, b) => a.localeCompare(b)));
  return out;
}

export function coverageGridAxes(
  rules: readonly MarketRuleRow[],
  outputOrder: readonly string[] = [],
): { markets: string[]; platforms: string[] } {
  const markets = orderCoverageMarkets(
    rules.map(ruleCanonical).filter(Boolean),
    outputOrder,
  );
  const platforms = orderCoveragePlatforms([
    ...SPORTSBOOKS,
    ...rules.map((row) => row.sportsbook),
  ]);
  return { markets, platforms };
}

function exchangeFor(
  exchanges: readonly LeagueExchange[],
  sportsbook: string,
): LeagueExchange | undefined {
  const book = normalizeCoverageSportsbook(sportsbook);
  return exchanges.find((ex) => normalizeCoverageSportsbook(ex.sportsbook || "") === book);
}

export function platformLeagueEnabled(
  detail: CoverageLeagueDetail,
  sportsbook: string,
): boolean {
  if (!detail.enabled) return false;
  const book = normalizeCoverageSportsbook(sportsbook);

  if (book === "optic") {
    return Boolean(String(detail.optic_league_id ?? "").trim());
  }

  const hit = exchangeFor(detail.exchanges, book);
  if (!hit || hit.enabled === false) return false;

  if (book === "novig" || book === "underdog" || book === "dkex") {
    return Boolean(nonEmpty(hit.settings?.league, hit.source_league_id));
  }
  if (book === "polymarket_usa") {
    return Boolean(nonEmpty(hit.settings?.slug_prefix, hit.source_league_id));
  }
  return true;
}

export function leaguePlatformEntryState(
  league: string,
  detail: CoverageLeagueDetail,
  sportsbook: string,
): EntryLocationState {
  const book = sportsbook.trim();
  return {
    fromRules: true,
    tab: "league",
    mode: "amend",
    league: league.trim(),
    sport: detail.sport || "",
    optic_league_id: detail.optic_league_id || "",
    fixture_source: detail.fixture_source || "api",
    fixture_horizon_hours: detail.fixture_horizon_hours,
    enabled: detail.enabled,
    entity_type: detail.entity_type || undefined,
    alias_enforcement: detail.alias_enforcement || undefined,
    runshop_enabled: detail.runshop_enabled,
    exchanges: [...detail.exchanges],
    focusSportsbook: book,
    note: `From Coverage: ${book}`,
  };
}

/** Editor league tab when coverage has a slug but no tip league_detail payload. */
export function coverageLeagueHeaderState(
  league: string,
  sportsbook: string,
  sport = "",
): EntryLocationState {
  const book = sportsbook.trim();
  return {
    fromRules: true,
    tab: "league",
    mode: "amend",
    league: league.trim(),
    sport: sport.trim(),
    focusSportsbook: book,
    note: `From Coverage: ${book}`,
  };
}

export function baselineToggles(rules: readonly MarketRuleRow[]): Record<CoverageCellKey, boolean> {
  const { markets, platforms } = coverageGridAxes(rules);
  const out: Record<CoverageCellKey, boolean> = {};
  for (const market of markets) {
    for (const book of platforms) {
      const cell = rulesForCell(rules, book, market);
      if (!cell.length) continue;
      out[coverageCellKey(book, market)] = cellIsOn(cell);
    }
  }
  return out;
}

export function dirtyToggleKeys(
  baseline: Record<CoverageCellKey, boolean>,
  toggles: Record<CoverageCellKey, boolean>,
): CoverageCellKey[] {
  return Object.keys(toggles).filter((key) => toggles[key] !== baseline[key]);
}

export function rowsForToggleChanges(
  rules: readonly MarketRuleRow[],
  baseline: Record<CoverageCellKey, boolean>,
  toggles: Record<CoverageCellKey, boolean>,
): { enableRows: MarketRuleRow[]; disableRows: MarketRuleRow[] } {
  const enableRows: MarketRuleRow[] = [];
  const disableRows: MarketRuleRow[] = [];
  for (const key of dirtyToggleKeys(baseline, toggles)) {
    const { sportsbook, canonical } = parseCoverageCellKey(key);
    const cell = rulesForCell(rules, sportsbook, canonical);
    if (toggles[key]) enableRows.push(...cell);
    else disableRows.push(...cell);
  }
  return { enableRows, disableRows };
}
