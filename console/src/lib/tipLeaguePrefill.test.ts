import { describe, expect, it } from "vitest";

import { DEFAULT_FIXTURE_HORIZON_HOURS } from "../entryEnums";
import type { LeagueRuleRow } from "../types";
import { leagueFormPrefill } from "./tipLeaguePrefill";

const epl: LeagueRuleRow = {
  league: "epl",
  league_label: "EPL",
  sport: "soccer",
  optic_league_id: "england_-_premier_league",
  fixture_source: "api",
  fixture_horizon_hours: 96,
  enabled: true,
  exchanges: [
    {
      sportsbook: "optic",
      enabled: true,
      parser_profile: "optic_standard_v1",
      source_league_id: "england_-_premier_league",
    },
  ],
};

describe("leagueFormPrefill", () => {
  it("copies tip horizon, optic, sport, and books for a matching slug", () => {
    const next = leagueFormPrefill({ slug: "epl", tip: epl });
    expect(next.sport).toBe("soccer");
    expect(next.opticLeagueId).toBe("england_-_premier_league");
    expect(next.fixtureHorizonHours).toBe(96);
    expect(next.exchanges).toEqual(epl.exchanges);
  });

  it("keeps location-state horizon instead of the tip (Proposed Edit)", () => {
    const next = leagueFormPrefill({
      slug: "epl",
      tip: epl,
      explicitHorizon: 168,
    });
    expect(next.fixtureHorizonHours).toBe(168);
    expect(next.opticLeagueId).toBe("england_-_premier_league");
  });

  it("fills optic/horizon/books when Coverage only passed sport", () => {
    const next = leagueFormPrefill({
      slug: "epl",
      tip: epl,
      explicitSport: "soccer",
    });
    expect(next.sport).toBe("soccer");
    expect(next.opticLeagueId).toBe("england_-_premier_league");
    expect(next.fixtureHorizonHours).toBe(96);
    expect(next.exchanges).toHaveLength(1);
  });

  it("does not invent fields for an unknown slug", () => {
    const next = leagueFormPrefill({ slug: "brand_new_cup" });
    expect(next).toEqual({});
  });

  it("does not fall back to the mapper default unless the slug is on the tip", () => {
    const next = leagueFormPrefill({ slug: "brand_new_cup", tip: epl });
    expect(next.fixtureHorizonHours).toBeUndefined();
    expect(DEFAULT_FIXTURE_HORIZON_HOURS).toBe(168);
  });
});
