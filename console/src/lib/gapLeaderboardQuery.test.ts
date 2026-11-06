import { describe, expect, it } from "vitest";

import { readGapLeaderboardQuery, writeGapLeaderboardQuery } from "./gapLeaderboardQuery";

describe("gapLeaderboardQuery", () => {
  it("defaults to 24h ranked by failed RFQs, every platform", () => {
    expect(readGapLeaderboardQuery(new URLSearchParams())).toEqual({
      hours: 24,
      platforms: [],
      markets: [],
      kickoffFrom: "",
      kickoffTo: "",
      sort: "demand",
      q: "",
    });
  });

  it("round-trips every filter and omits defaults", () => {
    const params = writeGapLeaderboardQuery(new URLSearchParams(), {
      hours: 6,
      platforms: ["kalshi", "crypto"],
      markets: ["Moneyline"],
      kickoffFrom: "2026-09-26T12:00",
      sort: "unmapped",
      q: "nhl",
    });
    expect(params.getAll("platform")).toEqual(["kalshi", "crypto"]);
    const state = readGapLeaderboardQuery(params);
    expect(state).toMatchObject({ hours: 6, markets: ["Moneyline"], kickoffFrom: "2026-09-26T12:00", sort: "unmapped" });
    expect(writeGapLeaderboardQuery(params, { hours: 24, sort: "demand" }).has("hours")).toBe(false);
  });

  it("falls back on an unknown window or sort", () => {
    const state = readGapLeaderboardQuery(new URLSearchParams("hours=7&sort=bogus"));
    expect([state.hours, state.sort]).toEqual([24, "demand"]);
  });
});
