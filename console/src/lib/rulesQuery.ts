/** URL state for the Rules explorer (search + multi-select filters + sort). */

export const CANONICAL_NONE = "__none__";

export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZE_OPTIONS)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 20;

export type RulesKind = "entities" | "leagues" | "market_rules";
export type SortDir = "asc" | "desc";
export const DEFAULT_RULES_KIND: RulesKind = "market_rules";

export type RulesQueryState = {
  kind: RulesKind;
  q: string;
  page: number;
  limit: PageSize;
  league: string[];
  sportsbook: string[];
  canonical: string[];
  action: string[];
  sort: string;
  dir: SortDir;
};

export function parseKind(raw: string | null): RulesKind {
  if (raw === "leagues" || raw === "market_rules" || raw === "entities") return raw;
  return DEFAULT_RULES_KIND;
}

export function parsePage(raw: string | null): number {
  const n = Number.parseInt(raw ?? "0", 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function parseLimit(raw: string | null): PageSize {
  const n = Number.parseInt(raw ?? "", 10);
  if (n === 20 || n === 50 || n === 100) return n;
  return DEFAULT_PAGE_SIZE;
}

export function parseList(params: URLSearchParams, key: string): string[] {
  return params
    .getAll(key)
    .flatMap((v) => v.split(","))
    .map((s) => s.trim())
    .filter(Boolean);
}

export function parseDir(raw: string | null): SortDir {
  return raw === "desc" ? "desc" : "asc";
}

export function readRulesQuery(params: URLSearchParams): RulesQueryState {
  return {
    kind: parseKind(params.get("kind")),
    q: params.get("q") ?? "",
    page: parsePage(params.get("page")),
    limit: parseLimit(params.get("limit")),
    league: parseList(params, "league"),
    sportsbook: parseList(params, "sportsbook"),
    canonical: parseList(params, "canonical"),
    action: parseList(params, "action"),
    sort: (params.get("sort") ?? "").trim(),
    dir: parseDir(params.get("dir")),
  };
}

function appendAll(params: URLSearchParams, key: string, values: string[]): void {
  for (const value of values) params.append(key, value);
}

export function writeRulesQuery(
  current: URLSearchParams,
  patch: Partial<RulesQueryState>,
): URLSearchParams {
  const next = { ...readRulesQuery(current), ...patch };
  const params = new URLSearchParams();
  params.set("kind", next.kind);
  if (next.q) params.set("q", next.q);
  if (next.page > 0) params.set("page", String(next.page));
  if (next.limit !== DEFAULT_PAGE_SIZE) params.set("limit", String(next.limit));
  appendAll(params, "league", next.league);
  appendAll(params, "sportsbook", next.sportsbook);
  appendAll(params, "canonical", next.canonical);
  appendAll(params, "action", next.action);
  if (next.sort) {
    params.set("sort", next.sort);
    if (next.dir === "desc") params.set("dir", "desc");
  }
  return params;
}

export function nextSort(currentSort: string, currentDir: SortDir, column: string): Pick<RulesQueryState, "sort" | "dir" | "page"> {
  if (currentSort === column) {
    return { sort: column, dir: currentDir === "asc" ? "desc" : "asc", page: 0 };
  }
  return { sort: column, dir: "asc", page: 0 };
}
