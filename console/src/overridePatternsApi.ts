/** Explore -> Override patterns: repeated mapping overrides as rule candidates. */

import { api } from "./api";

export type OverridePatternKind = "market_rule" | "alias";

export type OverridePattern = {
  cluster_id: string;
  kind: OverridePatternKind;
  sportsbook: string;
  league: string;
  optic_market_id: string;
  source_key_type: string;
  source_key: string;
  code: string;
  selection: string;
  games: number;
  overrides: number;
  active: number;
  sources: string[];
  sample_keys: string[];
  draft: { status: string; detail: string };
  proposed: boolean;
};

export type OverridePatternsResponse = {
  clusters: OverridePattern[];
  unparsed: Record<string, number>;
  error: string | null;
};

export type OverridePatternStageResult = {
  ok: boolean;
  error?: string;
  detail?: string;
  blockers?: string[];
  review?: { ref?: string };
};

export function listOverridePatterns(opts: {
  minGames: number;
  includeInactive: boolean;
  kind?: string;
  refresh?: boolean;
}) {
  const params = new URLSearchParams({ min_games: String(opts.minGames) });
  if (opts.includeInactive) params.set("include_inactive", "true");
  if (opts.kind) params.set("kind", opts.kind);
  if (opts.refresh) params.set("refresh", "true");
  return api<OverridePatternsResponse>(`/console/override-patterns?${params.toString()}`);
}

export function stageOverridePattern(clusterId: string, acknowledgeShadow: boolean) {
  return api<OverridePatternStageResult>("/console/override-patterns/stage", {
    method: "POST",
    body: JSON.stringify({ cluster_id: clusterId, acknowledge_shadow: acknowledgeShadow }),
  });
}
