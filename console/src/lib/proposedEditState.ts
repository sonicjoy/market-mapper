/** Map a Proposed mapping card onto Editor `/entry` location state. */

import type { EntryLocationState, MappingRow } from "../types";

type PrefillFields = EntryLocationState & { canonical?: string };

export function proposedEditState(row: MappingRow, returnTo?: string): EntryLocationState {
  const tab = row.kind === "league" ? "league" : row.kind === "market_rule" ? "market" : "alias";
  const base: EntryLocationState = {
    fromRules: true,
    mode: "amend",
    tab,
    league: row.league,
    sportsbook: row.sportsbook,
    code: row.source.code,
    entity_name: row.target.name,
    canonical_key: row.target.code,
    ...(returnTo ? { returnTo } : {}),
  };
  if (row.kind === "league") {
    return {
      ...base,
      tab: "league",
      sport: row.sport || "",
      optic_league_id: row.optic_league_id || row.target.id || "",
      fixture_source: row.fixture_source || "api",
      fixture_horizon_hours: row.fixture_horizon_hours,
      enabled: row.enabled,
      exchanges: row.exchanges ?? [],
      note: row.reason || "",
    };
  }
  if (row.kind !== "market_rule") return base;
  const ignore = isIgnoredMarketRule(row);
  return fillMarketPrefill({
    ...base,
    source_key: row.source.code,
    source_key_type: row.source.description,
    action: ignore ? "ignore" : "map",
    canonical_market_type: ignore ? null : marketRuleCanonical(row),
    official_description: row.official_description ?? null,
    citation_url: row.citation_url ?? null,
    note: row.notes ?? "",
    match_operator: row.match_operator || "exact",
    line_offset: row.line_offset ?? null,
    yes_side: row.yes_side ?? null,
    side_swap: row.side_swap ?? null,
  });
}

/** Mapper Chat `prefill_form` fields → Editor market dropdowns. */
export function fillMarketPrefill(fields: PrefillFields): EntryLocationState {
  if (fields.tab !== "market") return fields;
  const ignore = isIgnorePrefill(fields);
  const sourceKey = (fields.source_key || fields.code || "").trim();
  return {
    ...fields,
    source_key: sourceKey || fields.source_key,
    action: ignore ? "ignore" : fields.action || "map",
    canonical_market_type: ignore ? null : marketPrefillCanonical(fields),
  };
}

function isIgnoredMarketRule(row: MappingRow): boolean {
  const desc = (row.target.description || "").trim().toLowerCase();
  const name = (row.target.name || "").trim().toLowerCase();
  return desc === "ignore" || name === "ignored";
}

function isIgnorePrefill(fields: PrefillFields): boolean {
  const action = (fields.action || "").trim().toLowerCase();
  const name = (fields.entity_name || "").trim().toLowerCase();
  return action === "ignore" || name === "ignored" || name === "ignore";
}

function marketRuleCanonical(row: MappingRow): string | null {
  const name = (row.target.name || "").trim();
  if (name && name.toLowerCase() !== "ignored") return name;
  const desc = (row.target.description || "").trim();
  if (desc && desc.toLowerCase() !== "ignore") return desc;
  return null;
}

function marketPrefillCanonical(fields: PrefillFields): string | null {
  const direct = (fields.canonical_market_type || "").trim();
  if (direct) return direct;
  for (const raw of [fields.entity_name, fields.canonical_key, fields.canonical]) {
    const val = (raw || "").trim();
    if (val && val.toLowerCase() !== "ignored" && val.toLowerCase() !== "ignore") return val;
  }
  return null;
}
