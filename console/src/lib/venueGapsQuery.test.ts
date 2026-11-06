import { describe, expect, it } from "vitest";

import { readVenueGapsQuery, writeVenueGapsQuery } from "./venueGapsQuery";

describe("venueGapsQuery", () => {
  it("defaults to crypto, live, unmapped only, sorted by unmapped", () => {
    expect(readVenueGapsQuery(new URLSearchParams())).toEqual({
      platform: "crypto",
      phase: "live",
      q: "",
      unmappedOnly: true,
      sort: "unmapped",
      markets: [],
      kickoffFrom: "",
      kickoffTo: "",
    });
  });

  it("omits defaults and round-trips the rest", () => {
    const empty = writeVenueGapsQuery(new URLSearchParams(), {
      platform: "crypto",
      phase: "live",
      unmappedOnly: true,
      sort: "unmapped",
    });
    expect(empty.toString()).toBe("");
    const params = writeVenueGapsQuery(new URLSearchParams(), {
      phase: "pre",
      q: "epl",
      unmappedOnly: false,
      sort: "demand",
    });
    expect(params.toString()).toBe("phase=pre&q=epl&all=1&sort=demand");
    expect(readVenueGapsQuery(params)).toMatchObject({ phase: "pre", q: "epl", unmappedOnly: false, sort: "demand" });
  });

  it("falls back on an unknown sort", () => {
    expect(readVenueGapsQuery(new URLSearchParams("sort=bogus")).sort).toBe("unmapped");
  });

  it("round-trips picked markets and the kickoff window", () => {
    const params = writeVenueGapsQuery(new URLSearchParams(), {
      markets: ["Moneyline", "Passing Yards"],
      kickoffFrom: "2026-09-26T12:00",
      kickoffTo: "2026-09-27T00:00",
    });
    expect(params.getAll("market")).toEqual(["Moneyline", "Passing Yards"]);
    const state = readVenueGapsQuery(params);
    expect(state.markets).toEqual(["Moneyline", "Passing Yards"]);
    expect(state.kickoffFrom).toBe("2026-09-26T12:00");
    expect(state.kickoffTo).toBe("2026-09-27T00:00");
    expect(writeVenueGapsQuery(params, { kickoffFrom: "", kickoffTo: "" }).has("from")).toBe(false);
  });
});
