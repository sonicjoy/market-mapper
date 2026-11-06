export type CatalogLookupKey = {
  sportsbook: string;
  source_market_id: string;
  source_selection_id: string;
};

export type CatalogOverrideFields = {
  gameId: string;
  marketId: string;
  selection: string;
  selectionLine: string;
  points: number;
  selectionPoints: number;
  groupingKey: string;
};

export type CatalogFormSlice = CatalogOverrideFields & {
  sportsbook: string;
  sourceMarketId: string;
  sourceSelectionId: string;
  reason: string;
  mappingSource: string;
};

export const EMPTY_OVERRIDE_FIELDS: CatalogOverrideFields = {
  gameId: "",
  marketId: "",
  selection: "",
  selectionLine: "",
  points: 0,
  selectionPoints: 0,
  groupingKey: "default",
};

export const CATALOG_ROW_FIELDS: Array<{ key: string; label: string }> = [
  { key: "game_id", label: "game_id" },
  { key: "market_id", label: "market_id" },
  { key: "selection", label: "selection" },
  { key: "selection_line", label: "selection_line" },
  { key: "points", label: "points" },
  { key: "selection_points", label: "selection_points" },
  { key: "grouping_key", label: "grouping_key" },
  { key: "rank_class", label: "rank_class" },
  { key: "mapping_source", label: "mapping_source" },
  { key: "is_rfq_winner", label: "is_rfq_winner" },
  { key: "is_mapping_override", label: "is_mapping_override" },
  { key: "in_rank_window", label: "in_rank_window" },
  { key: "start_date", label: "start_date" },
  { key: "src_market_id", label: "src_market_id" },
  { key: "src_selection_id", label: "src_selection_id" },
];

export function buildLookupKey(form: {
  sportsbook: string;
  sourceMarketId: string;
  sourceSelectionId: string;
}): CatalogLookupKey {
  return {
    sportsbook: form.sportsbook,
    source_market_id: form.sourceMarketId.trim(),
    source_selection_id: form.sourceSelectionId.trim(),
  };
}

export function lookupKeysEqual(
  current: CatalogLookupKey | null,
  next: CatalogLookupKey,
): boolean {
  return (
    current !== null
    && current.sportsbook === next.sportsbook
    && current.source_market_id.trim().toLowerCase()
      === next.source_market_id.trim().toLowerCase()
    && current.source_selection_id.trim().toLowerCase()
      === next.source_selection_id.trim().toLowerCase()
  );
}

export function isLookupCurrent(
  lookupKey: CatalogLookupKey | null,
  form: Pick<CatalogFormSlice, "sportsbook" | "sourceMarketId" | "sourceSelectionId">,
): boolean {
  return lookupKeysEqual(lookupKey, buildLookupKey(form));
}

/** Kalshi tickers are opaque ids: the selection id is typed, never parsed from the ticker. */
export function prepareCatalogLookup<T extends CatalogFormSlice>(form: T): T {
  return { ...form, sourceSelectionId: form.sourceSelectionId.trim() };
}

export function catalogLookupChanged(
  lookupKey: CatalogLookupKey | null,
  nextForm: Pick<CatalogFormSlice, "sportsbook" | "sourceMarketId" | "sourceSelectionId">,
): boolean {
  return lookupKey !== null && !lookupKeysEqual(lookupKey, buildLookupKey(nextForm));
}

export function applyCatalogPrefill<T extends CatalogFormSlice>(
  prev: T,
  data: {
    winner?: Record<string, unknown> | null;
    resolved_source_market_id?: string;
    resolved_source_selection_id?: string;
    source_market_id?: string;
    source_selection_id?: string;
  },
): T {
  const resolved = resolvedSourceIdsFromLookup(data);
  const next = {
    ...prev,
    sourceMarketId: resolved.sourceMarketId,
    sourceSelectionId: resolved.sourceSelectionId,
  };
  const winnerFields = winnerFromLookup(data.winner);
  if (winnerFields) {
    return {
      ...next,
      ...winnerFields,
      mappingSource: String(data.winner?.mapping_source ?? ""),
    };
  }
  return { ...next, ...EMPTY_OVERRIDE_FIELDS, mappingSource: "" };
}

export function resolvedSourceIdsFromLookup(data: {
  resolved_source_market_id?: string;
  resolved_source_selection_id?: string;
  source_market_id?: string;
  source_selection_id?: string;
}): { sourceMarketId: string; sourceSelectionId: string } {
  return {
    sourceMarketId: data.resolved_source_market_id ?? data.source_market_id ?? "",
    sourceSelectionId: data.resolved_source_selection_id ?? data.source_selection_id ?? "",
  };
}

const LANE_KEY_HINTS: Record<string, string> = {
  "crypto.com":
    "Source market id = the FIX symbol (NX.F.OPT...); leave selection id blank. Lands in market_mapping at the next mapping pipeline run (every 15 min), then crypto.com's 10-min reload.",
  "Polymarket (USA)":
    "Source market id = the instrument symbol; selection id = yes (this Optic selection is the LONG side) or no (the complement). Publish both sides of a two-way market. Lands at the next mapping pipeline run (every 15 min).",
};

/** How to key an override for a market_mapping-lane venue; null when the lane is off or the book is not a lane venue. */
export function laneKeyHint(sportsbook: string, laneEnabled: boolean | undefined): string | null {
  if (!laneEnabled) return null;
  return LANE_KEY_HINTS[sportsbook] ?? null;
}

export function overrideFormIssues(form: CatalogFormSlice): string[] {
  const issues: string[] = [];
  if (!form.gameId.trim()) issues.push("game_id");
  if (!form.marketId.trim()) issues.push("market_id (Optic)");
  if (!form.selection.trim()) issues.push("selection");
  if (!form.sourceMarketId.trim()) issues.push("source market id");
  if (!form.groupingKey.trim()) issues.push("grouping_key");
  if (!form.reason.trim()) issues.push("reason");
  if (!Number.isFinite(form.points)) issues.push("points");
  if (!Number.isFinite(form.selectionPoints)) issues.push("selection_points");
  return issues;
}

export function overrideFormReady(form: CatalogFormSlice): boolean {
  return overrideFormIssues(form).length === 0;
}

export function overrideFormDisabledReason(form: CatalogFormSlice): string | null {
  const issues = overrideFormIssues(form);
  if (issues.length === 0) return null;
  return `Fill required override fields: ${issues.join(", ")}.`;
}

export function canSubmitCatalogOverride(args: {
  form: CatalogFormSlice;
  lookupKey: CatalogLookupKey | null;
  lookupSuccess: boolean;
}): boolean {
  return (
    overrideFormReady(args.form)
    && isLookupCurrent(args.lookupKey, args.form)
    && args.lookupSuccess
  );
}

export const canPublishCatalogOverride = canSubmitCatalogOverride;
export const canDeactivateCatalogOverride = canSubmitCatalogOverride;

export function submitDisabledReason(args: {
  lookupKey: CatalogLookupKey | null;
  lookupSuccess: boolean;
  form: CatalogFormSlice;
}): string | null {
  if (!isLookupCurrent(args.lookupKey, args.form)) {
    return "Look up the current RFQ key before publishing or deactivating.";
  }
  if (!args.lookupSuccess) {
    return "Complete a successful lookup before publishing or deactivating.";
  }
  return null;
}

export const publishDisabledReason = submitDisabledReason;
export const deactivateDisabledReason = submitDisabledReason;

export function lookupFailedReason(args: {
  lookupKey: CatalogLookupKey | null;
  form: Pick<CatalogFormSlice, "sportsbook" | "sourceMarketId" | "sourceSelectionId">;
  isError: boolean;
  errorMessage?: string;
}): string | null {
  if (!args.lookupKey || !args.isError) return null;
  if (!isLookupCurrent(args.lookupKey, args.form)) return null;
  return args.errorMessage ?? "Catalog lookup failed.";
}

export function outsideRankWindowWarning(args: {
  candidateCount: number;
  inRankWindow: boolean | null | undefined;
}): string | null {
  if (args.candidateCount <= 0 || args.inRankWindow === true) return null;
  return (
    "OOM row start_date is outside the live rank window; fold+rank will not restamp. "
    + "Active publish still requires game_id in opticodds_fixtures within 4h..14d. "
    + "Deactivate may still be accepted."
  );
}

export function lookupFeedbackClass(data: {
  candidate_count: number;
  in_rank_window: boolean | null;
} | undefined): string {
  if (!data || data.candidate_count === 0) {
    return "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300";
  }
  if (data.in_rank_window !== true) {
    return "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100";
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100";
}

export function winnerPanelClass(inRankWindow: boolean | null | undefined): string {
  if (inRankWindow !== true) {
    return "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100";
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100";
}

export function winnerPanelTitle(
  winner: Record<string, unknown> | null | undefined,
  inRankWindow: boolean | null | undefined,
): string {
  if (winner?.is_rfq_winner === true) {
    return inRankWindow === true ? "Winner" : "Winner (outside rank window)";
  }
  return inRankWindow === true ? "Mapped row" : "Mapped row (outside rank window)";
}

export function formatCatalogRowValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function catalogRowSummary(
  row: Record<string, unknown> | null | undefined,
): Array<{ label: string; value: string }> {
  if (!row) return [];
  return CATALOG_ROW_FIELDS.flatMap(({ key, label }) => {
    if (!(key in row)) return [];
    return [{ label, value: formatCatalogRowValue(row[key]) }];
  });
}

export function winnerFromLookup(
  winner: Record<string, unknown> | null | undefined,
): CatalogOverrideFields | null {
  if (!winner || typeof winner !== "object") return null;
  return {
    gameId: String(winner.game_id ?? ""),
    marketId: String(winner.market_id ?? ""),
    selection: String(winner.selection ?? ""),
    selectionLine: String(winner.selection_line ?? ""),
    points: Number.isFinite(Number(winner.points)) ? Number(winner.points) : 0,
    selectionPoints: Number.isFinite(Number(winner.selection_points))
      ? Number(winner.selection_points)
      : 0,
    groupingKey: String(winner.grouping_key ?? "default"),
  };
}

export function winnerPrefillKey(
  lookupKey: CatalogLookupKey,
  winner: Record<string, unknown> | null | undefined,
): string {
  const fields = winnerFromLookup(winner);
  if (!fields) {
    return `${lookupKey.sportsbook}|${lookupKey.source_market_id}|${lookupKey.source_selection_id}|empty`;
  }
  return [
    lookupKey.sportsbook,
    lookupKey.source_market_id,
    lookupKey.source_selection_id,
    fields.gameId,
    fields.marketId,
    fields.selection,
    fields.selectionLine,
    fields.points,
    fields.selectionPoints,
    fields.groupingKey,
    String(winner?.mapping_source ?? ""),
  ].join("|");
}

/** Why an active override for this sportsbook would be a no-op (its consumer never reads opticodds_mapping). */
export function unreadOverrideReason(
  unread: Record<string, string> | undefined,
  sportsbook: string,
): string | null {
  const want = sportsbook.trim().toLowerCase();
  if (!want || !unread) return null;
  const hit = Object.entries(unread).find(([name]) => name.toLowerCase() === want);
  return hit ? hit[1] : null;
}
