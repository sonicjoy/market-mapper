/** Persist Explore-page filters in sessionStorage (same store as Proposed). */

import { readSessionItem, removeSessionItem, writeSessionItem } from "./sessionStore";

export const PAGE_FILTER_PREFIX = "mapping-console-filters:";

export type FilterPage =
  | "rules"
  | "coverage"
  | "unmapped"
  | "missing"
  | "venue-gaps"
  | "gap-leaderboard"
  | "mapping-risk";

const FILTER_PAGES: Record<string, FilterPage> = {
  "/rules": "rules",
  "/coverage": "coverage",
  "/unmapped": "unmapped",
  "/missing": "missing",
  "/venue-gaps": "venue-gaps",
  "/gap-leaderboard": "gap-leaderboard",
  "/mapping-risk": "mapping-risk",
};

export function pageFilterStorageKey(page: FilterPage): string {
  return `${PAGE_FILTER_PREFIX}${page}`;
}

export function readPageFilters(page: FilterPage): URLSearchParams | null {
  const raw = readSessionItem(pageFilterStorageKey(page));
  if (raw == null || raw === "") return null;
  return new URLSearchParams(raw);
}

export function writePageFilters(page: FilterPage, params: URLSearchParams): void {
  const key = pageFilterStorageKey(page);
  const qs = params.toString();
  if (!qs) {
    removeSessionItem(key);
    return;
  }
  writeSessionItem(key, qs);
}

/** Restore saved filters only when the live URL has no filter keys (dock / bare path). */
export function hydratePageFilters(
  params: URLSearchParams,
  saved: URLSearchParams | null,
): URLSearchParams | null {
  if (!saved || isEmptyParams(saved) || !isEmptyParams(params)) return null;
  return new URLSearchParams(saved);
}

export function pathWithSavedFilters(path: string): string {
  const page = FILTER_PAGES[path];
  if (!page) return path;
  const saved = readPageFilters(page);
  const qs = saved?.toString();
  return qs ? `${path}?${qs}` : path;
}

/** Keep the current query when re-clicking the active dock item; else restore last filters. */
export function dockPath(path: string, pathname: string, search: string): string {
  if (pathname === path) {
    return search ? `${path}${search}` : path;
  }
  return pathWithSavedFilters(path);
}

function isEmptyParams(params: URLSearchParams): boolean {
  return [...params.keys()].length === 0;
}
