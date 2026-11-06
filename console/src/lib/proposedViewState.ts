/** Persist Proposed-card working view across Editor trips (sessionStorage). */

import { parseKindFilter, showsFixtures, type ProposedKindFilter } from "./proposedRail";
import { readSessionItem, removeSessionItem, writeSessionItem } from "./sessionStore";

export type ProposedViewSnapshot = {
  league: string;
  fixture: string;
  kind: ProposedKindFilter;
  hideOptic: boolean;
  kept: string[];
};

const STORAGE_PREFIX = "mapping-console-proposed-view:";

export function proposedViewStorageKey(ref: string): string {
  return `${STORAGE_PREFIX}${ref}`;
}

export function parseProposedViewSnapshot(raw: unknown): ProposedViewSnapshot | null {
  const row = typeof raw === "string" ? parseJson(raw) : raw;
  if (!row || typeof row !== "object" || Array.isArray(row)) return null;
  const rec = row as Record<string, unknown>;
  const kind = parseKindFilter(typeof rec.kind === "string" ? rec.kind : null);
  return {
    league: asString(rec.league),
    fixture: asString(rec.fixture),
    kind,
    hideOptic: rec.hideOptic === true,
    kept: asStringArray(rec.kept),
  };
}

export function hydrateProposedSearchParams(
  params: URLSearchParams,
  saved: ProposedViewSnapshot | null,
): URLSearchParams | null {
  if (!saved) return null;
  const next = new URLSearchParams(params);
  let changed = false;
  if (!next.get("league") && saved.league) {
    next.set("league", saved.league);
    changed = true;
  }
  if (!next.get("kind") && saved.kind !== "all") {
    next.set("kind", saved.kind);
    changed = true;
  }
  const kind = parseKindFilter(next.get("kind"));
  if (showsFixtures(kind) && !next.get("fixture") && saved.fixture) {
    next.set("fixture", saved.fixture);
    changed = true;
  }
  return changed ? next : null;
}

export function proposedReturnPath(
  ref: string,
  view: { league: string; fixture: string; kind: ProposedKindFilter },
): string {
  const params = new URLSearchParams();
  if (view.league) params.set("league", view.league);
  if (view.kind !== "all") params.set("kind", view.kind);
  if (view.fixture && showsFixtures(view.kind)) params.set("fixture", view.fixture);
  const qs = params.toString();
  return qs ? `/review/${ref}?${qs}` : `/review/${ref}`;
}

export function isProposedReturnTo(path: string | undefined | null): boolean {
  if (!path) return false;
  if (path.includes("://") || path.includes("\\") || path.includes("..")) return false;
  return /^\/review\/[^/?#]+(\?.*)?$/.test(path);
}

export function readProposedViewState(ref: string): ProposedViewSnapshot | null {
  if (!ref) return null;
  try {
    return parseProposedViewSnapshot(readSessionItem(proposedViewStorageKey(ref)));
  } catch {
    return null;
  }
}

export function writeProposedViewState(ref: string, snap: ProposedViewSnapshot): void {
  if (!ref) return;
  writeSessionItem(proposedViewStorageKey(ref), JSON.stringify(snap));
}

export function clearProposedViewState(ref: string): void {
  if (!ref) return;
  removeSessionItem(proposedViewStorageKey(ref));
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}
