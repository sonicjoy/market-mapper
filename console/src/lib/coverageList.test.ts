import { describe, expect, it } from "vitest";

import {
  COVERAGE_PAGE_SIZE,
  filterFixturesByName,
  formatFixtureStart,
  lastPageIndex,
  pageOf,
  parseCoveragePage,
  readCoverageQuery,
  writeCoverageQuery,
} from "./coverageList";
import type { CoverageFixture } from "../types";

function fx(label: string, extra: Partial<CoverageFixture> = {}): CoverageFixture {
  return { fixture_id: label, label, ...extra };
}

describe("filterFixturesByName", () => {
  const rows = [
    fx("Luciano Darderi vs Dalibor Svrcina", { home: "Luciano Darderi", away: "Dalibor Svrcina" }),
    fx("Chelsea vs Arsenal", { home: "Chelsea", away: "Arsenal" }),
  ];

  it("returns all when query is empty", () => {
    expect(filterFixturesByName(rows, "  ")).toHaveLength(2);
  });

  it("matches label or side names", () => {
    expect(filterFixturesByName(rows, "darderi").map((r) => r.label)).toEqual([
      "Luciano Darderi vs Dalibor Svrcina",
    ]);
    expect(filterFixturesByName(rows, "ARSENAL").map((r) => r.fixture_id)).toEqual([
      "Chelsea vs Arsenal",
    ]);
  });
});

describe("pageOf", () => {
  const items = Array.from({ length: 22 }, (_, i) => i);

  it("uses 10 per page", () => {
    expect(COVERAGE_PAGE_SIZE).toBe(10);
    expect(pageOf(items, 0, COVERAGE_PAGE_SIZE)).toEqual(items.slice(0, 10));
    expect(pageOf(items, 2, COVERAGE_PAGE_SIZE)).toEqual([20, 21]);
  });
});

describe("lastPageIndex", () => {
  it("clamps empty lists to page 0", () => {
    expect(lastPageIndex(0, 10)).toBe(0);
  });

  it("counts full pages", () => {
    expect(lastPageIndex(10, 10)).toBe(0);
    expect(lastPageIndex(11, 10)).toBe(1);
  });
});

describe("parseCoveragePage", () => {
  it("reads a non-negative page index", () => {
    expect(parseCoveragePage(null)).toBe(0);
    expect(parseCoveragePage("2")).toBe(2);
    expect(parseCoveragePage("-1")).toBe(0);
    expect(parseCoveragePage("nope")).toBe(0);
  });
});

describe("coverage query URL", () => {
  it("omits empty filters and page 0", () => {
    const params = writeCoverageQuery(new URLSearchParams(), {
      sport: "tennis",
      league: "atp",
      fixture: "fx1",
      q: "sinner",
      phase: "live",
      page: 0,
    });
    expect(params.toString()).toBe("sport=tennis&league=atp&fixture=fx1&q=sinner");
  });

  it("reads page and fixture search from the URL", () => {
    expect(readCoverageQuery(new URLSearchParams("q=sinner&page=3"))).toEqual({
      sport: "",
      league: "",
      fixture: "",
      q: "sinner",
      phase: "live",
      page: 3,
    });
  });

  it("round-trips pre phase", () => {
    const params = writeCoverageQuery(new URLSearchParams(), { phase: "pre" });
    expect(params.toString()).toBe("phase=pre");
    expect(readCoverageQuery(params).phase).toBe("pre");
  });
});

describe("formatFixtureStart", () => {
  it("formats UTC kickoff", () => {
    expect(formatFixtureStart("2026-09-05T14:30:00Z")).toBe("2026-09-05 14:30 UTC");
  });

  it("uses TBD when missing", () => {
    expect(formatFixtureStart("")).toBe("TBD");
    expect(formatFixtureStart(undefined)).toBe("TBD");
  });
});
