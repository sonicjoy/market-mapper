import { describe, expect, it } from "vitest";

import { DEFAULT_PAGE_SIZE } from "./rulesQuery";
import { DEFAULT_UNMAPPED_SORT, readUnmappedQuery, writeUnmappedQuery } from "./unmappedQuery";

describe("unmappedQuery", () => {
  it("omits default sort, dir, page, and limit from the URL", () => {
    const params = writeUnmappedQuery(new URLSearchParams(), {
      q: "nantes",
      sport: "soccer",
      league: "ligue_1",
      platform: "kalshi",
      sort: DEFAULT_UNMAPPED_SORT,
      dir: "asc",
      page: 0,
      limit: DEFAULT_PAGE_SIZE,
    });
    expect(params.toString()).toBe("q=nantes&sport=soccer&league=ligue_1&platform=kalshi");
  });

  it("round-trips sort, desc dir, page, and page size", () => {
    const params = writeUnmappedQuery(new URLSearchParams(), {
      sort: "demand",
      dir: "desc",
      page: 2,
      limit: 50,
    });
    expect(readUnmappedQuery(params)).toEqual({
      platform: "",
      sport: "",
      league: "",
      q: "",
      phase: "live",
      sort: "demand",
      dir: "desc",
      page: 2,
      limit: 50,
    });
  });

  it("defaults missing sort to start", () => {
    expect(readUnmappedQuery(new URLSearchParams("dir=desc")).sort).toBe(DEFAULT_UNMAPPED_SORT);
    expect(readUnmappedQuery(new URLSearchParams("dir=desc")).dir).toBe("desc");
  });

  it("round-trips pre phase", () => {
    const params = writeUnmappedQuery(new URLSearchParams(), { phase: "pre" });
    expect(params.toString()).toBe("phase=pre");
    expect(readUnmappedQuery(params).phase).toBe("pre");
  });
});
