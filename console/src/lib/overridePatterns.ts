/** Pure helpers for Override patterns: verdict copy, shape label, URL state. */

import type { OverridePattern } from "../overridePatternsApi";

export const DEFAULT_MIN_GAMES = 3;

export type VerdictTone = "go" | "info" | "warn" | "stop";

type Verdict = { text: string; tone: VerdictTone };

/** Kernel verdict -> what the operator should conclude. Unknown codes fall through verbatim. */
const VERDICTS: Record<string, Verdict> = {
  draftable: { text: "Rule can be proposed", tone: "go" },
  already_mapped: { text: "Rule already exists - these overrides cover something else (names, lines)", tone: "info" },
  already_live: { text: "Alias already live - these overrides look redundant", tone: "info" },
  already_ignored: { text: "Tip IGNORES this market type, yet overrides keep it live - conflict", tone: "stop" },
  code_owned_by_other: { text: "Code already belongs to another entity - not safe to alias", tone: "stop" },
  no_optic_canonical: { text: "Kernel cannot bind this market type to the Optic market - Editor", tone: "warn" },
  needs_code: { text: "Optic market has no MarketType in code yet", tone: "warn" },
  overlay_unwired: { text: "No overlay would apply this rule", tone: "warn" },
  no_tip_entity: { text: "No tip entity for this name - onboard it in Editor", tone: "warn" },
  ambiguous_entity: { text: "Several tip entities fit this name", tone: "warn" },
  league_not_on_tip: { text: "League or venue not on the tip", tone: "warn" },
  verify_blocked: { text: "Cart verify blocked it", tone: "stop" },
  dry_run_blocked: { text: "Dry-run blocked it", tone: "stop" },
  not_evaluated: { text: "Not evaluated (beyond the first clusters)", tone: "info" },
};

export function verdictFor(status: string): Verdict {
  return VERDICTS[status] ?? { text: status || "unknown", tone: "warn" };
}

/** `btts-1h -> 1h_btts` or `KCC -> Kansas City Chiefs`. */
export function shapeLabel(row: OverridePattern): string {
  if (row.kind === "market_rule") return `${row.source_key} -> ${row.optic_market_id}`;
  return `${row.code} -> ${row.selection}`;
}

/**
 * Only a pattern the kernel drafted AND verified can be proposed. Owner, 2026-09-26: no bypass
 * when operators agree but the kernel refuses; show a strong warning with the reason instead.
 */
export function canPropose(row: OverridePattern): boolean {
  return row.draft.status === "draftable" && !row.proposed;
}

export type PatternWarning = { title: string; why: string; todo: string };

const WARNINGS: Record<string, PatternWarning> = {
  no_optic_canonical: {
    title: "Repeated overrides, but no rule will be proposed",
    why:
      "Operators keep pinning this venue market to the same Optic market, but the rules kernel cannot bind the two by name. " +
      "A rule is applied league-wide to every future fixture with no per-fixture check, so a rule written without that " +
      "binding could misprice every fixture it touches. Agreement between operators is not proof the pairing is right.",
    todo:
      "Check a sample of these overrides against the Optic market. If the pairing is right, add the market mapping in " +
      "Editor (it runs the dry-run); if not, deactivate the overrides.",
  },
  already_ignored: {
    title: "Conflict: the rules ignore this market, the overrides keep it live",
    why:
      "The tip deliberately ignores this market type, yet active overrides are still mapping it, so these fixtures are " +
      "being priced on overrides alone, with no rule behind them.",
    todo:
      "Decide which is right: if the ignore is wrong, remove it in Editor; if it is right, deactivate these overrides.",
  },
  code_owned_by_other: {
    title: "Not safe to alias: the code already belongs to another entity",
    why:
      "This venue code is already an alias of a different entity in this league. Aliasing it again would silently remap " +
      "that entity's markets as well.",
    todo: "Check which entity the code really is; fix the existing alias in Editor if it is wrong.",
  },
  verify_blocked: {
    title: "The Cart checks rejected this rule",
    why: "The same verify gate Cart runs refused the drafted rule. Proposing it anyway would skip that check.",
    todo: "Read the detail below; fix the underlying rule in Editor, then re-check here.",
  },
  dry_run_blocked: {
    title: "The dry-run rejected this rule",
    why: "Applying the drafted rule in a dry-run changed or broke other mappings, so it is not proposed.",
    todo: "Read the detail below; fix the underlying rule in Editor, then re-check here.",
  },
};

/** Strong warning for a pattern that repeats but must not become a rule automatically; null otherwise. */
export function warningFor(row: OverridePattern): PatternWarning | null {
  return WARNINGS[row.draft.status] ?? null;
}

export type OverridePatternsQuery = { kind: "" | "market_rule" | "alias"; minGames: number; includeInactive: boolean };

export function readOverridePatternsQuery(params: URLSearchParams): OverridePatternsQuery {
  const kindRaw = params.get("kind") ?? "";
  const n = Number.parseInt(params.get("min_games") ?? "", 10);
  return {
    kind: kindRaw === "market_rule" || kindRaw === "alias" ? kindRaw : "",
    minGames: Number.isFinite(n) && n >= 1 ? n : DEFAULT_MIN_GAMES,
    includeInactive: params.get("inactive") === "1",
  };
}

export function writeOverridePatternsQuery(
  current: URLSearchParams,
  patch: Partial<OverridePatternsQuery>,
): URLSearchParams {
  const next = { ...readOverridePatternsQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.kind) params.set("kind", next.kind);
  if (next.minGames !== DEFAULT_MIN_GAMES) params.set("min_games", String(next.minGames));
  if (next.includeInactive) params.set("inactive", "1");
  return params;
}
