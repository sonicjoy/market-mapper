/** Map a staging-cart row onto Mapper `/entry` location state. */

import type { CartItem } from "../cartStore";
import type { EntryLocationState } from "../types";
import { pinsFromPayload } from "./marketRules";

function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (value == null) return "";
  return String(value).trim();
}

function asOptionalNumber(value: unknown): number | null {
  if (value == null || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function asOptionalBool(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  if (value == null || value === "") return null;
  const text = String(value).trim().toLowerCase();
  if (text === "true" || text === "yes" || text === "1") return true;
  if (text === "false" || text === "no" || text === "0") return false;
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function firstAlias(payload: Record<string, unknown>): Record<string, unknown> | null {
  const raw = payload.aliases;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  return asRecord(raw[0]);
}

function leagueState(item: CartItem): EntryLocationState {
  const p = item.payload;
  const exchanges = Array.isArray(p.exchanges)
    ? (p.exchanges.filter((row) => asRecord(row)) as Record<string, unknown>[])
    : [];
  const horizon = p.fixture_horizon_hours;
  return {
    tab: "league",
    cartItemId: item.id,
    league: asText(p.league),
    sport: asText(p.sport),
    optic_league_id: asText(p.optic_league_id),
    fixture_source: asText(p.fixture_source) || "api",
    fixture_horizon_hours:
      typeof horizon === "number" && Number.isFinite(horizon) ? horizon : undefined,
    enabled: p.enabled !== false,
    exchanges,
    note: asText(p.notes) || asText(p.note),
  };
}

function aliasState(item: CartItem): EntryLocationState {
  const p = item.payload;
  const alias = firstAlias(p);
  return {
    tab: "alias",
    cartItemId: item.id,
    league: asText(p.league),
    sportsbook: asText(alias?.sportsbook),
    code: asText(alias?.alias_value),
    entity_name: asText(p.canonical_name),
    entity_type: asText(p.entity_type) || "team",
    canonical_key: asText(p.canonical_key),
    alias_kind: asText(alias?.alias_kind),
    note: asText(p.notes) || asText(p.note),
  };
}

function marketState(item: CartItem): EntryLocationState {
  const p = item.payload;
  const pin = pinsFromPayload(p)[0] ?? {};
  return {
    tab: "market",
    cartItemId: item.id,
    league: asText(p.league),
    sportsbook: asText(pin.sportsbook),
    source_key: asText(pin.source_key),
    action: asText(pin.action) || "map",
    canonical_market_type: asText(pin.canonical_market_type) || null,
    source_key_type: asText(pin.source_key_type),
    official_description: asText(pin.official_description) || null,
    citation_url: asText(pin.citation_url) || null,
    note: asText(pin.notes) || asText(p.notes) || asText(p.note),
    match_operator: asText(pin.match_operator) || "exact",
    line_offset: asOptionalNumber(pin.line_offset),
    yes_side: asText(pin.yes_side) || null,
    side_swap: asOptionalBool(pin.side_swap),
  };
}

export function cartItemToEntryState(item: CartItem): EntryLocationState {
  switch (item.kind) {
    case "mapping_league":
      return leagueState(item);
    case "entity_alias":
      return aliasState(item);
    case "mapping_market_rules":
      return marketState(item);
    default: {
      const _exhaustive: never = item.kind;
      return _exhaustive;
    }
  }
}
