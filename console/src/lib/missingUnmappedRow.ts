import type { MissingSymbolRow, UnmappedLegRow } from "../types";

/** Map a Missing catalogue row to the Unmapped Why / stage API shape. */
export function missingRowToUnmapped(row: MissingSymbolRow): UnmappedLegRow {
  const type = [
    row.market_group,
    row.contract_type,
    row.period_type ? `@ ${row.period_type}` : "",
  ]
    .filter(Boolean)
    .join(" / ")
    .replace(" / @", " @");
  const desc = row.fixture_name
    ? type
      ? `${row.fixture_name} — ${type}`
      : row.fixture_name
    : row.symbol;
  return {
    platform: row.platform,
    key: row.symbol,
    platform_leg_description: desc,
    demand: 0,
    league: row.league || null,
    fixture: row.fixture_name || null,
    sport: row.sport || null,
    start_date: row.kickoff || undefined,
    market_group: row.market_group || undefined,
    contract_type: row.contract_type || undefined,
  };
}
