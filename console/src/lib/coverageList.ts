import type { FixturePhase } from "../components/FixturePhaseTabs";
import { DEFAULT_FIXTURE_PHASE, parseFixturePhase } from "../components/FixturePhaseTabs";
import type { CoverageFixture } from "../types";

export const COVERAGE_PAGE_SIZES = [10, 25, 50] as const;
export type CoveragePageSize = (typeof COVERAGE_PAGE_SIZES)[number];
export const COVERAGE_PAGE_SIZE: CoveragePageSize = 10;

export function parseCoveragePageSize(raw: string): CoveragePageSize {
  const n = Number.parseInt(raw, 10);
  if (n === 10 || n === 25 || n === 50) {
    return n;
  }
  return COVERAGE_PAGE_SIZE;
}

export function filterFixturesByName(
  fixtures: readonly CoverageFixture[],
  q: string,
): CoverageFixture[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [...fixtures];
  return fixtures.filter((fx) => {
    const hay = [fx.label, fx.home, fx.away]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(needle);
  });
}

export function pageOf<T>(items: readonly T[], page: number, size: number): T[] {
  const start = Math.max(0, page) * size;
  return items.slice(start, start + size);
}

export type CoverageQueryState = {
  sport: string;
  league: string;
  fixture: string;
  q: string;
  phase: FixturePhase;
  page: number;
};

export function parseCoveragePage(raw: string | null | undefined): number {
  const n = Number.parseInt(raw ?? "0", 10);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.floor(n);
}

export function readCoverageQuery(params: URLSearchParams): CoverageQueryState {
  return {
    sport: params.get("sport") ?? "",
    league: params.get("league") ?? "",
    fixture: params.get("fixture") ?? "",
    q: params.get("q") ?? "",
    phase: parseFixturePhase(params.get("phase")),
    page: parseCoveragePage(params.get("page")),
  };
}

export function writeCoverageQuery(
  current: URLSearchParams,
  patch: Partial<CoverageQueryState>,
): URLSearchParams {
  const next = { ...readCoverageQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.sport) params.set("sport", next.sport);
  if (next.league) params.set("league", next.league);
  if (next.fixture) params.set("fixture", next.fixture);
  if (next.q) params.set("q", next.q);
  if (next.phase !== DEFAULT_FIXTURE_PHASE) params.set("phase", next.phase);
  if (next.page > 0) params.set("page", String(next.page));
  return params;
}

export function lastPageIndex(count: number, size: number): number {
  if (count <= 0) return 0;
  return Math.max(0, Math.ceil(count / size) - 1);
}

export function formatFixtureStart(iso?: string | null): string {
  const raw = (iso ?? "").trim();
  if (!raw) return "TBD";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  const utc = parsed.toISOString();
  return `${utc.slice(0, 10)} ${utc.slice(11, 16)} UTC`;
}
