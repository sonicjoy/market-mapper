/** Market-rule cart labels and bulk ignore↔map staging helpers. */

import { sourceKeyTypeFor } from "../entryEnums";
import type { MarketRuleRow } from "../types";

export type LooseMarketPin = {
  sportsbook?: unknown;
  source_key?: unknown;
  source_key_type?: unknown;
  action?: unknown;
  canonical_market_type?: unknown;
  official_description?: unknown;
  citation_url?: unknown;
  notes?: unknown;
  match_operator?: unknown;
  line_offset?: unknown;
  yes_side?: unknown;
  side_swap?: unknown;
  card_label?: unknown;
  card?: { label?: unknown };
};

export type MarketRuleCartItem = {
  label: string;
  payload: Record<string, unknown>;
};

export type BulkMarketOp = "enable" | "disable";
export type SelectionOp = BulkMarketOp | "mixed" | "empty";

export type StageSelectionResult = {
  op: SelectionOp;
  cartItems: MarketRuleCartItem[];
  skippedUnknown: string[];
  stagedCount: number;
};

function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (value == null) return "";
  return String(value).trim();
}

export function marketRuleRowKey(row: MarketRuleRow): string {
  return `${row.league}|${row.sportsbook}|${row.source_key_type}|${row.source_key}`;
}

export function pinAction(pin: LooseMarketPin): "map" | "ignore" {
  const action = asText(pin.action) || "map";
  const canonical = asText(pin.canonical_market_type);
  if (action === "ignore" || !canonical) return "ignore";
  return "map";
}

export function formatMarketRulePin(pin: LooseMarketPin): string {
  const book = asText(pin.sportsbook) || "unknown";
  const key = asText(pin.source_key) || "?";
  if (pinAction(pin) === "ignore") return `${book} ${key} (ignore)`;
  return `${book} ${key} → ${asText(pin.canonical_market_type)} (map)`;
}

export function pinsFromPayload(payload: Record<string, unknown>): LooseMarketPin[] {
  const rules = payload.rules;
  if (!Array.isArray(rules)) return [];
  return rules.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object");
}

export function cartMarketRuleLines(payload: Record<string, unknown>): string[] {
  return pinsFromPayload(payload).map((pin) => formatMarketRulePin(pin));
}

function cardLabel(pin: LooseMarketPin | undefined): string {
  if (!pin) return "";
  const direct = asText(pin.card_label);
  if (direct) return direct;
  return asText(pin.card?.label);
}

export function formatMarketRuleCartLabel(league: string, pins: LooseMarketPin[]): string {
  const slug = league.trim();
  const first = pins[0];
  const fromCard = pins.length === 1 ? cardLabel(first) : "";
  if (fromCard) return fromCard;
  if (first && pins.length === 1) {
    const line = formatMarketRulePin(first);
    return slug ? `${slug} · ${line}` : line;
  }
  if (pins.length > 1) {
    const actions = new Set(pins.map(pinAction));
    const action = actions.size === 1 ? [...actions][0] : "rules";
    const tally = `${pins.length} ${action}`;
    return slug ? `${slug} (${tally})` : tally;
  }
  if (slug) return `Market rules ${slug}`;
  return "Market rules";
}

export function canonicalForEnable(row: MarketRuleRow): string | null {
  const existing = (row.canonical_market_type ?? "").trim();
  return existing || null;
}

export function selectionOp(rows: MarketRuleRow[]): SelectionOp {
  if (rows.length === 0) return "empty";
  const actions = new Set(rows.map((row) => row.action));
  if (actions.size !== 1) return "mixed";
  if (actions.has("ignore")) return "enable";
  if (actions.has("map")) return "disable";
  return "mixed";
}

function pinFromRow(
  row: MarketRuleRow,
  action: "map" | "ignore",
  canonical: string | null,
): Record<string, unknown> {
  const league = row.league.trim();
  const sportsbook = row.sportsbook.trim();
  return {
    sportsbook,
    rule_kind: row.rule_kind || "taxonomy",
    source_key_type: row.source_key_type || sourceKeyTypeFor(sportsbook),
    source_key: row.source_key,
    action,
    canonical_market_type: canonical,
    league,
    enabled: true,
    confidence: "manual",
    match_operator: row.match_operator || "exact",
    line_offset: row.line_offset ?? null,
    yes_side: row.yes_side ?? null,
    side_swap: row.side_swap ?? null,
    official_description: row.official_description ?? null,
    citation_url: row.citation_url ?? null,
    notes: row.notes ?? null,
  };
}

function rowLabel(row: MarketRuleRow): string {
  return [row.league.trim(), row.sportsbook.trim(), row.source_key.trim() || "(missing source key)"]
    .filter(Boolean)
    .join(" ");
}

function cartItemsFromPins(byLeague: Map<string, Record<string, unknown>[]>): MarketRuleCartItem[] {
  const cartItems: MarketRuleCartItem[] = [];
  for (const [league, pins] of byLeague) {
    cartItems.push({
      label: formatMarketRuleCartLabel(league, pins),
      payload: { kind: "mapping_market_rules", league, rules: pins },
    });
  }
  return cartItems;
}

function stageEnable(rows: MarketRuleRow[]): StageSelectionResult {
  const skippedUnknown: string[] = [];
  const byLeague = new Map<string, Record<string, unknown>[]>();
  for (const row of rows) {
    const league = row.league.trim();
    const canonical = canonicalForEnable(row);
    if (!league || !canonical) {
      skippedUnknown.push(rowLabel(row));
      continue;
    }
    const pins = byLeague.get(league) ?? [];
    pins.push(pinFromRow(row, "map", canonical));
    byLeague.set(league, pins);
  }
  const cartItems = cartItemsFromPins(byLeague);
  return {
    op: "enable",
    cartItems,
    skippedUnknown,
    stagedCount: cartItems.reduce((n, item) => n + pinsFromPayload(item.payload).length, 0),
  };
}

function stageDisable(rows: MarketRuleRow[]): StageSelectionResult {
  const skippedUnknown: string[] = [];
  const byLeague = new Map<string, Record<string, unknown>[]>();
  for (const row of rows) {
    const league = row.league.trim();
    if (!league) {
      skippedUnknown.push(rowLabel(row));
      continue;
    }
    const pins = byLeague.get(league) ?? [];
    pins.push(pinFromRow(row, "ignore", null));
    byLeague.set(league, pins);
  }
  const cartItems = cartItemsFromPins(byLeague);
  return {
    op: "disable",
    cartItems,
    skippedUnknown,
    stagedCount: cartItems.reduce((n, item) => n + pinsFromPayload(item.payload).length, 0),
  };
}

export function stageMarketRuleToggles(
  enableRows: MarketRuleRow[],
  disableRows: MarketRuleRow[],
): StageSelectionResult {
  const enabled = enableRows.length
    ? stageEnable(enableRows)
    : { op: "enable" as const, cartItems: [], skippedUnknown: [], stagedCount: 0 };
  const disabled = disableRows.length
    ? stageDisable(disableRows)
    : { op: "disable" as const, cartItems: [], skippedUnknown: [], stagedCount: 0 };
  const op: SelectionOp =
    enableRows.length && disableRows.length
      ? "enable"
      : disableRows.length
        ? "disable"
        : enableRows.length
          ? "enable"
          : "empty";
  return {
    op,
    cartItems: [...enabled.cartItems, ...disabled.cartItems],
    skippedUnknown: [...enabled.skippedUnknown, ...disabled.skippedUnknown],
    stagedCount: enabled.stagedCount + disabled.stagedCount,
  };
}

export function coverageToggleMessage(result: StageSelectionResult): string {
  if (!result.stagedCount) {
    return result.skippedUnknown.length
      ? `No market-rule changes to add. Skipped: ${result.skippedUnknown.join(", ")}.`
      : "No market-rule changes to add.";
  }
  const parts = [`Added ${result.stagedCount} market rule(s) to cart.`];
  if (result.skippedUnknown.length) {
    parts.push(`Skipped: ${result.skippedUnknown.join(", ")}.`);
  }
  return parts.join(" ");
}

export function stageSelectedMarketRules(rows: MarketRuleRow[]): StageSelectionResult {
  const op = selectionOp(rows);
  if (op === "enable") return stageEnable(rows);
  if (op === "disable") return stageDisable(rows);
  return { op, cartItems: [], skippedUnknown: [], stagedCount: 0 };
}

export function stageSelectionMessage(result: StageSelectionResult): string {
  if (result.op === "mixed") return "Select only ignored or only mapped rules.";
  if (result.op === "empty") return "Select ignored or mapped rules first.";
  const verb = result.op === "enable" ? "enabled" : "ignored";
  const parts: string[] = [];
  if (result.stagedCount) {
    parts.push(`Added ${result.stagedCount} market rule(s) to cart (${verb}).`);
  } else {
    parts.push(result.op === "enable" ? "No ignore rules could be enabled." : "No mapped rules could be ignored.");
  }
  if (result.skippedUnknown.length) {
    parts.push(
      result.op === "enable"
        ? `Skipped (no canonical type): ${result.skippedUnknown.join(", ")}.`
        : `Skipped: ${result.skippedUnknown.join(", ")}.`,
    );
  }
  return parts.join(" ");
}
