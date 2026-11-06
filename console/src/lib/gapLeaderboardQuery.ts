/** URL state for Gap leaderboard (window + platforms + markets + kickoff window + sort + search). */

export const GAP_WINDOWS = [3, 6, 12, 24, 48] as const;
export const DEFAULT_GAP_WINDOW = 24;

export const GAP_SORTS = [
  { value: "demand", label: "Failed RFQs" },
  { value: "unmapped", label: "Unmapped selections" },
] as const;

export type GapSort = (typeof GAP_SORTS)[number]["value"];
export const DEFAULT_GAP_SORT: GapSort = "demand";

export type GapLeaderboardQueryState = {
  hours: number;
  platforms: string[];
  markets: string[];
  /** Kickoff window bounds, UTC wall time as `YYYY-MM-DDTHH:MM` (datetime-local shape). */
  kickoffFrom: string;
  kickoffTo: string;
  sort: GapSort;
  q: string;
};

function parseHours(raw: string | null): number {
  const n = Number.parseInt(raw ?? "", 10);
  return (GAP_WINDOWS as readonly number[]).includes(n) ? n : DEFAULT_GAP_WINDOW;
}

function parseSort(raw: string | null): GapSort {
  return GAP_SORTS.find((row) => row.value === raw)?.value ?? DEFAULT_GAP_SORT;
}

function all(params: URLSearchParams, key: string): string[] {
  return params
    .getAll(key)
    .map((v) => v.trim())
    .filter(Boolean);
}

export function readGapLeaderboardQuery(params: URLSearchParams): GapLeaderboardQueryState {
  return {
    hours: parseHours(params.get("hours")),
    platforms: all(params, "platform"),
    markets: all(params, "market"),
    kickoffFrom: params.get("from") ?? "",
    kickoffTo: params.get("to") ?? "",
    sort: parseSort(params.get("sort")),
    q: params.get("q") ?? "",
  };
}

export function writeGapLeaderboardQuery(
  current: URLSearchParams,
  patch: Partial<GapLeaderboardQueryState>,
): URLSearchParams {
  const next = { ...readGapLeaderboardQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.hours !== DEFAULT_GAP_WINDOW) params.set("hours", String(next.hours));
  for (const value of next.platforms) params.append("platform", value);
  for (const value of next.markets) params.append("market", value);
  if (next.kickoffFrom) params.set("from", next.kickoffFrom);
  if (next.kickoffTo) params.set("to", next.kickoffTo);
  if (next.sort !== DEFAULT_GAP_SORT) params.set("sort", next.sort);
  if (next.q) params.set("q", next.q);
  return params;
}
