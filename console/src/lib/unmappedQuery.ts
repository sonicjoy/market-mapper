/** URL state for Unmapped (search + sport/league/book + sort). */

import {
  DEFAULT_FIXTURE_PHASE,
  parseFixturePhase,
  type FixturePhase,
} from "../components/FixturePhaseTabs";
import {
  DEFAULT_PAGE_SIZE,
  parseDir,
  parseLimit,
  parsePage,
  type PageSize,
  type SortDir,
} from "./rulesQuery";

export const DEFAULT_UNMAPPED_SORT = "start";

export type UnmappedQueryState = {
  platform: string;
  sport: string;
  league: string;
  q: string;
  phase: FixturePhase;
  sort: string;
  dir: SortDir;
  page: number;
  limit: PageSize;
};

export function readUnmappedQuery(params: URLSearchParams): UnmappedQueryState {
  const sort = (params.get("sort") ?? "").trim() || DEFAULT_UNMAPPED_SORT;
  return {
    platform: params.get("platform") ?? "",
    sport: params.get("sport") ?? "",
    league: params.get("league") ?? "",
    q: params.get("q") ?? "",
    phase: parseFixturePhase(params.get("phase")),
    sort,
    dir: parseDir(params.get("dir")),
    page: parsePage(params.get("page")),
    limit: parseLimit(params.get("limit")),
  };
}

export function writeUnmappedQuery(
  current: URLSearchParams,
  patch: Partial<UnmappedQueryState>,
): URLSearchParams {
  const next = { ...readUnmappedQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.q) params.set("q", next.q);
  if (next.sport) params.set("sport", next.sport);
  if (next.league) params.set("league", next.league);
  if (next.platform) params.set("platform", next.platform);
  if (next.phase !== DEFAULT_FIXTURE_PHASE) params.set("phase", next.phase);
  if (next.sort !== DEFAULT_UNMAPPED_SORT) params.set("sort", next.sort);
  if (next.dir === "desc") params.set("dir", "desc");
  if (next.page > 0) params.set("page", String(next.page));
  if (next.limit !== DEFAULT_PAGE_SIZE) params.set("limit", String(next.limit));
  return params;
}
