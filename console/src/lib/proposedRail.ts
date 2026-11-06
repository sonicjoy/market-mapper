import type { MappingRow, ProposedFixture, ProposedLeagueBlock } from "../types";
import { isAiNoteRef, isAiSuggestMarker } from "./aiSuggestDisplay";
import { isOpticMapping } from "./mappingDisplay";

export type RailSelection =
  | { type: "league"; league: string }
  | { type: "fixture"; league: string; fixtureId: string };

export type ProposedKindFilter = "all" | "alias" | "league" | "market_rule" | "ai" | "override";

export const KIND_FILTERS: { id: ProposedKindFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "alias", label: "Aliases" },
  { id: "league", label: "Leagues" },
  { id: "market_rule", label: "Market rules" },
  { id: "ai", label: "AI Guesses" },
  { id: "override", label: "Override patterns" },
];

/** Marker Explore -> Override patterns stamps on every pin it proposes. */
const OVERRIDE_CLUSTER_REF = "override_cluster:";

export function isOverridePatternRow(row: { evidence: string[] }): boolean {
  return row.evidence.some((ref) => ref.includes(OVERRIDE_CLUSTER_REF));
}

export function parseKindFilter(raw: string | null): ProposedKindFilter {
  switch (raw) {
    case "alias":
    case "league":
    case "market_rule":
    case "ai":
    case "override":
      return raw;
    default:
      return "all";
  }
}

export function isCloneBundle(row: { key: string }): boolean {
  return row.key.startsWith("clone:");
}

export function rowsForKind(rows: MappingRow[], kind: ProposedKindFilter): MappingRow[] {
  switch (kind) {
    case "all":
      return rows;
    case "alias":
      return rows.filter((row) => row.kind === "alias");
    case "league":
      return rows.filter((row) => row.kind === "league");
    case "market_rule":
      return rows.filter((row) => row.kind === "market_rule");
    case "ai":
      return rows.filter(isAiGuessRow);
    case "override":
      return rows.filter(isOverridePatternRow);
    default: {
      const _exhaustive: never = kind;
      return _exhaustive;
    }
  }
}

export function defaultKeep(row: MappingRow, kept: Set<string>): boolean {
  if (kept.has(row.key)) return true;
  if (kept.has(`drop:${row.key}`)) return false;
  if (isAiGuessRow(row)) return row.keep_default;
  return row.tier === "confirmed" && row.keep_default;
}

export function isAiSuggestRow(row: { tier: string; evidence: string[] }): boolean {
  if (row.tier === "ai") return true;
  return row.evidence.some((ref) => isAiSuggestMarker(ref) || isAiNoteRef(ref));
}

export function isAiGuessRow(row: { tier: string; evidence: string[] }): boolean {
  return row.tier === "guess" || isAiSuggestRow(row);
}

export function showsFixtures(kind: ProposedKindFilter): boolean {
  return kind === "all" || kind === "alias" || kind === "ai";
}

export function markKeep(kept: Set<string>, key: string): Set<string> {
  const next = new Set(kept);
  next.delete(`drop:${key}`);
  next.add(key);
  return next;
}

export function markDrop(kept: Set<string>, key: string): Set<string> {
  const next = new Set(kept);
  next.delete(key);
  next.add(`drop:${key}`);
  return next;
}

export function leagueRows(
  block: ProposedLeagueBlock,
  allRows: MappingRow[] = block.rows,
): MappingRow[] {
  const fromAll = allRows.filter((row) => row.league === block.league);
  return fromAll.length > 0 ? fromAll : block.rows;
}

export function fixtureSides(label: string): string[] {
  return label
    .split(/\s+vs\.?\s+/i)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function nameOnSide(target: string, side: string): boolean {
  const needle = target.trim().toLowerCase();
  const hay = side.trim().toLowerCase();
  if (!needle || !hay) return false;
  if (needle === hay) return true;
  return ` ${hay} `.includes(` ${needle} `);
}

export function aliasRelatedToFixture(
  row: MappingRow,
  fixtureId: string,
  fixtureLabel?: string,
): boolean {
  if (row.kind !== "alias") return false;
  if (row.next_fixtures.some((fx) => fx.fixture_id === fixtureId)) return true;
  if (!fixtureLabel) return false;
  const targetName = row.target?.name;
  if (!targetName) return false;
  return fixtureSides(fixtureLabel).some((side) => nameOnSide(targetName, side));
}

export function rowsForSelection(
  block: ProposedLeagueBlock,
  selection: RailSelection,
  allRows: MappingRow[] = block.rows,
): MappingRow[] {
  const rows = leagueRows(block, allRows);
  if (selection.type === "league") {
    return rows;
  }
  const fixtureLabel = block.fixtures.find((fx) => fx.fixture_id === selection.fixtureId)?.label;
  return rows.filter((row) => aliasRelatedToFixture(row, selection.fixtureId, fixtureLabel));
}

export function rowsHidingOptic(rows: MappingRow[], hideOptic: boolean): MappingRow[] {
  return hideOptic ? rows.filter((row) => !isOpticMapping(row)) : rows;
}

export function visibleLeaguePills(
  leagues: readonly { league: string; league_label: string; is_new: boolean }[],
  allRows: MappingRow[],
  kind: ProposedKindFilter,
  hideOptic: boolean,
): { id: string; label: string }[] {
  return leagues.flatMap((lg) => {
    const n = rowsHidingOptic(
      rowsForKind(
        allRows.filter((row) => row.league === lg.league),
        kind,
      ),
      hideOptic,
    ).length;
    return n > 0
      ? [{ id: lg.league, label: leaguePillLabel(lg.league_label, n, lg.is_new) }]
      : [];
  });
}

export function pickVisibleLeague(
  pills: readonly { id: string }[],
  requestedLeague: string,
): string {
  if (pills.some((pill) => pill.id === requestedLeague)) return requestedLeague;
  return pills[0]?.id ?? requestedLeague;
}

export function approveCount(rows: MappingRow[], kept: Set<string>): number {
  return rows.filter((row) => defaultKeep(row, kept)).length;
}

export function guessPending(rows: MappingRow[], kept: Set<string>): number {
  return rows.filter(
    (row) => isAiGuessRow(row) && !defaultKeep(row, kept),
  ).length;
}

export function otherLeagueScope(
  rows: MappingRow[],
  currentLeague: string,
  kept: Set<string>,
): string {
  const other = rows.filter((row) => row.league !== currentLeague);
  if (other.length === 0) return "";
  const leagues = new Set(other.map((row) => row.league_label || row.league));
  const n = other.filter((row) => defaultKeep(row, kept)).length;
  const k = leagues.size;
  return ` · also ${n} items in ${k} other league${k === 1 ? "" : "s"}`;
}

export function formatTtko(hours: number | null | undefined): string {
  if (hours == null || Number.isNaN(hours)) return "TBD";
  const abs = Math.abs(hours);
  const mag =
    abs < 1
      ? `${Math.round(abs * 60)}m`
      : abs < 48
        ? `${Math.round(abs)}h`
        : `${Math.round(abs / 24)}d`;
  if (hours < 0 && !mag.startsWith("0")) return `-${mag}`;
  return mag;
}

export function formatOpticTtko(
  opticStatus?: string | null,
  ttkoHours?: number | null,
): string {
  const parts: string[] = [];
  const status = (opticStatus ?? "").trim();
  if (status) parts.push(status);
  if (ttkoHours != null && !Number.isNaN(ttkoHours)) {
    parts.push(formatTtko(ttkoHours));
  }
  return parts.join(" · ");
}

export function fixtureRfqVolume(
  fx: ProposedFixture,
  related: MappingRow[] = [],
): number {
  if (fx.rfq_demand && fx.rfq_demand > 0) return fx.rfq_demand;
  return related.reduce((max, row) => Math.max(max, row.rfq_demand ?? 0), 0);
}

export function leaguePillLabel(label: string, count: number, isNew = false): string {
  const base = isNew ? `${label} · new` : label;
  return `${base} · ${count}`;
}

export function formatRailMeta(
  ttkoHours: number | null | undefined,
  rfqDemand: number | null | undefined,
  pinCount: number,
): string {
  const parts = [formatTtko(ttkoHours)];
  if (rfqDemand && rfqDemand > 0) parts.push(`${rfqDemand} RFQ`);
  if (pinCount > 0) parts.push(`${pinCount} pin${pinCount === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

export function dropsForApprove(rows: MappingRow[], kept: Set<string>): { kind: string; key: string }[] {
  return rows
    .filter((row) => !defaultKeep(row, kept))
    .map((row) => ({ kind: row.kind, key: row.key }));
}
