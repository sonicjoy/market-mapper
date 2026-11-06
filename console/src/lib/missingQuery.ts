/** URL state for Missing (catalogue minus market_mapping). */

import {
  DEFAULT_PAGE_SIZE,
  parseDir,
  parseLimit,
  parsePage,
  type PageSize,
  type SortDir,
} from "./rulesQuery";

export const DEFAULT_MISSING_SORT = "kickoff";
export type MissingScope = "all" | "untouched" | "extra";

/** Operator label for catalogue scope (API: untouched | extra). */
export function missingScopeLabel(scope: "untouched" | "extra"): string {
  return scope === "untouched" ? "Fixture" : "Market";
}

export type MissingQueryState = {
  platform: string;
  sport: string;
  league: string;
  scope: MissingScope;
  marketGroup: string;
  /** Market names (catalogue contract_type); empty means all. */
  contractTypes: string[];
  /** Kickoff window bounds, UTC wall time as `YYYY-MM-DDTHH:MM` (datetime-local shape). */
  kickoffFrom: string;
  kickoffTo: string;
  q: string;
  sort: string;
  dir: SortDir;
  page: number;
  limit: PageSize;
};

export function readMissingQuery(params: URLSearchParams): MissingQueryState {
  const sort = (params.get("sort") ?? "").trim() || DEFAULT_MISSING_SORT;
  const scopeRaw = (params.get("scope") ?? "all").trim();
  const scope: MissingScope =
    scopeRaw === "untouched" || scopeRaw === "extra" ? scopeRaw : "all";
  return {
    platform: params.get("platform") ?? "crypto",
    sport: params.get("sport") ?? "",
    league: params.get("league") ?? "",
    scope,
    marketGroup: params.get("market_group") ?? "",
    contractTypes: params
      .getAll("contract_type")
      .map((v) => v.trim())
      .filter(Boolean),
    kickoffFrom: params.get("from") ?? "",
    kickoffTo: params.get("to") ?? "",
    q: params.get("q") ?? "",
    sort,
    dir: parseDir(params.get("dir")),
    page: parsePage(params.get("page")),
    limit: parseLimit(params.get("limit")),
  };
}

export function writeMissingQuery(
  current: URLSearchParams,
  patch: Partial<MissingQueryState>,
): URLSearchParams {
  const next = { ...readMissingQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.q) params.set("q", next.q);
  if (next.sport) params.set("sport", next.sport);
  if (next.league) params.set("league", next.league);
  if (next.platform && next.platform !== "crypto") params.set("platform", next.platform);
  if (next.scope !== "all") params.set("scope", next.scope);
  if (next.marketGroup) params.set("market_group", next.marketGroup);
  for (const value of next.contractTypes) params.append("contract_type", value);
  if (next.kickoffFrom) params.set("from", next.kickoffFrom);
  if (next.kickoffTo) params.set("to", next.kickoffTo);
  if (next.sort !== DEFAULT_MISSING_SORT) params.set("sort", next.sort);
  if (next.dir === "desc") params.set("dir", "desc");
  if (next.page > 0) params.set("page", String(next.page));
  if (next.limit !== DEFAULT_PAGE_SIZE) params.set("limit", String(next.limit));
  return params;
}
