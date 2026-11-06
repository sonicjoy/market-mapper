import { describe, expect, it } from "vitest";

import { missingScopeLabel, readMissingQuery, writeMissingQuery } from "./missingQuery";

describe("missingQuery", () => {
  it("defaults platform to crypto and scope to all", () => {
    const state = readMissingQuery(new URLSearchParams());
    expect(state.platform).toBe("crypto");
    expect(state.scope).toBe("all");
  });

  it("labels scope for the table", () => {
    expect(missingScopeLabel("untouched")).toBe("Fixture");
    expect(missingScopeLabel("extra")).toBe("Market");
  });

  it("round-trips scope and filters", () => {
    const params = writeMissingQuery(new URLSearchParams(), {
      scope: "untouched",
      league: "mlb",
      q: "Orioles",
      sort: "symbol",
      dir: "desc",
      page: 2,
    });
    const state = readMissingQuery(params);
    expect(state.scope).toBe("untouched");
    expect(state.league).toBe("mlb");
    expect(state.q).toBe("Orioles");
    expect(state.sort).toBe("symbol");
    expect(state.dir).toBe("desc");
    expect(state.page).toBe(2);
  });

  it("round-trips market names and the kickoff window", () => {
    const params = writeMissingQuery(new URLSearchParams(), {
      contractTypes: ["Moneyline", "Total RBIs"],
      kickoffFrom: "2026-09-26T12:00",
      kickoffTo: "2026-09-27T06:30",
    });
    expect(params.getAll("contract_type")).toEqual(["Moneyline", "Total RBIs"]);
    expect(params.get("from")).toBe("2026-09-26T12:00");
    const state = readMissingQuery(params);
    expect(state.contractTypes).toEqual(["Moneyline", "Total RBIs"]);
    expect(state.kickoffFrom).toBe("2026-09-26T12:00");
    expect(state.kickoffTo).toBe("2026-09-27T06:30");
  });

  it("reads an old single contract_type link as one market", () => {
    const state = readMissingQuery(new URLSearchParams("contract_type=Spread"));
    expect(state.contractTypes).toEqual(["Spread"]);
    expect(state.kickoffFrom).toBe("");
  });

  it("drops cleared window bounds from the URL", () => {
    const start = writeMissingQuery(new URLSearchParams(), { kickoffFrom: "2026-09-26T12:00" });
    const cleared = writeMissingQuery(start, { kickoffFrom: "" });
    expect(cleared.has("from")).toBe(false);
  });
});
