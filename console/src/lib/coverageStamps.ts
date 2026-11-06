import { sportsbookLabel } from "../entryEnums";
import {
  coverageCellKey,
  normalizeCoverageSportsbook,
  orderCoverageMarkets,
  orderCoveragePlatforms,
} from "./coverageMarketGrid";
import type { CoverageStampRow } from "../types";

export type StampFocus = {
  canonical: string;
  sportsbook?: string;
};

export type StampInspectState = {
  openCanonical: string | null;
  stampBook: string;
  stampQuery: string;
};

/** Click same book×canonical stamp link again to collapse; otherwise open with that filter. */
export function nextStampInspectState(
  current: StampInspectState,
  focus: StampFocus,
): StampInspectState {
  const canonical = focus.canonical.trim();
  const book = normalizeCoverageSportsbook(focus.sportsbook ?? "");
  if (current.openCanonical === canonical && current.stampBook === book) {
    return { openCanonical: null, stampBook: "", stampQuery: "" };
  }
  return { openCanonical: canonical, stampBook: book, stampQuery: "" };
}

export type StampSection = {
  canonical: string;
  rows: CoverageStampRow[];
  bookCounts: Record<string, number>;
};

export function stampCellKey(sportsbook: string, canonical: string): string {
  return coverageCellKey(sportsbook, canonical);
}

export function stampCountsByCell(stamps: readonly CoverageStampRow[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const row of stamps) {
    const canonical = (row.market_type || "").trim();
    const book = normalizeCoverageSportsbook(row.sportsbook || "");
    if (!canonical || !book) continue;
    const key = stampCellKey(book, canonical);
    out.set(key, (out.get(key) ?? 0) + 1);
  }
  return out;
}

export function groupStampsByCanonical(
  stamps: readonly CoverageStampRow[],
  canonicals: readonly string[],
): StampSection[] {
  const byCanonical = new Map<string, CoverageStampRow[]>();
  for (const row of stamps) {
    const canonical = (row.market_type || "").trim();
    if (!canonical) continue;
    const bucket = byCanonical.get(canonical) ?? [];
    bucket.push(row);
    byCanonical.set(canonical, bucket);
  }
  const ordered = orderCoverageMarkets(
    [...new Set([...canonicals, ...byCanonical.keys()])],
    canonicals,
  );
  return ordered.map((canonical) => {
    const rows = sortStampRows(byCanonical.get(canonical) ?? []);
    const bookCounts: Record<string, number> = {};
    for (const row of rows) {
      const book = normalizeCoverageSportsbook(row.sportsbook || "");
      if (!book) continue;
      bookCounts[book] = (bookCounts[book] ?? 0) + 1;
    }
    return { canonical, rows, bookCounts };
  });
}

export function stampBooks(stamps: readonly CoverageStampRow[]): string[] {
  return orderCoveragePlatforms(stamps.map((row) => row.sportsbook));
}

export function filterStampSections(
  sections: readonly StampSection[],
  opts: {
    book?: string;
    query?: string;
    focus?: StampFocus | null;
  },
): StampSection[] {
  const book = normalizeCoverageSportsbook(opts.book || "");
  const query = (opts.query || "").trim().toLowerCase();
  const focusCanonical = (opts.focus?.canonical || "").trim();
  const focusBook = normalizeCoverageSportsbook(opts.focus?.sportsbook || "");
  return sections
    .map((section) => {
      if (focusCanonical && section.canonical !== focusCanonical) {
        return { ...section, rows: [] };
      }
      const rows = section.rows.filter((row) => {
        const rowBook = normalizeCoverageSportsbook(row.sportsbook || "");
        if (book && rowBook !== book) return false;
        if (focusBook && rowBook !== focusBook) return false;
        if (!query) return true;
        const hay = [
          row.sportsbook,
          row.sportsbook_label,
          row.market_id,
          row.entity,
          row.line,
          row.side,
          row.contract_side,
          row.source_id,
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(query);
      });
      return { ...section, rows };
    })
    .filter((section) => !focusCanonical || section.canonical === focusCanonical);
}

export function formatStampUpdated(value?: string | null): string {
  const text = (value || "").trim();
  if (!text) return "—";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function stampBookSummary(bookCounts: Record<string, number>): string {
  const parts = Object.entries(bookCounts)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([book, count]) => `${sportsbookLabel(book)} ${count}`);
  return parts.join(" · ");
}

function sortStampRows(rows: readonly CoverageStampRow[]): CoverageStampRow[] {
  return [...rows].sort((a, b) => {
    const bookCmp = (a.sportsbook || "").localeCompare(b.sportsbook || "");
    if (bookCmp !== 0) return bookCmp;
    const entityCmp = (a.entity || "").localeCompare(b.entity || "");
    if (entityCmp !== 0) return entityCmp;
    const lineCmp = (a.line || "").localeCompare(b.line || "");
    if (lineCmp !== 0) return lineCmp;
    const sideCmp = (a.side || "").localeCompare(b.side || "");
    if (sideCmp !== 0) return sideCmp;
    const contractCmp = (a.contract_side || "").localeCompare(b.contract_side || "");
    if (contractCmp !== 0) return contractCmp;
    return (a.source_id || "").localeCompare(b.source_id || "");
  });
}
