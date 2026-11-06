import { describe, expect, it } from "vitest";

import { impliedPair, readMappingRiskQuery, writeMappingRiskQuery } from "./mappingRiskQuery";

describe("mappingRiskQuery", () => {
  it("defaults to every venue, every tier, not flagged-only", () => {
    const state = readMappingRiskQuery(new URLSearchParams());
    expect(state).toMatchObject({ platform: "", tier: "", reason: "", flagged: false, page: 0 });
  });

  it("round-trips filters and drops an unknown tier", () => {
    const params = writeMappingRiskQuery(new URLSearchParams(), {
      platform: "kalshi",
      tier: "high",
      reason: "ai_flagged",
      kickoffFrom: "2026-09-26T12:00",
      flagged: true,
      page: 2,
    });
    expect(readMappingRiskQuery(params)).toMatchObject({
      platform: "kalshi",
      tier: "high",
      reason: "ai_flagged",
      kickoffFrom: "2026-09-26T12:00",
      flagged: true,
      page: 2,
    });
    expect(readMappingRiskQuery(new URLSearchParams("tier=severe")).tier).toBe("");
  });

  it("formats implied probabilities, or nothing when a side is missing", () => {
    expect(impliedPair(1.25, 2.5)).toBe("80% vs 40%");
    expect(impliedPair(null, 2.5)).toBeNull();
    expect(impliedPair(1.0, 2.5)).toBeNull();
  });
});
