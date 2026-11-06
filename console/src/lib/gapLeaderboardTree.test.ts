import { describe, expect, it } from "vitest";

import type { GapFixture, GapLeague, GapPlatform } from "../gapLeaderboardApi";
import { searchPlatforms } from "./gapLeaderboardTree";

function fixture(key: string, name: string, market: string): GapFixture {
  return {
    fixture_key: key,
    name,
    start_date: null,
    ttko_hours: null,
    kickoff_date_only: false,
    catalogue_total: null,
    last_seen: null,
    fix_link: null,
    demand: 1,
    legs: 1,
    unmapped: 1,
    markets: [{ market, demand: 1, legs: 1, unmapped: 1, catalogue_total: null, last_seen: null, fix_link: null }],
  };
}

function league(label: string, fixtures: GapFixture[]): GapLeague {
  return { key: label, label, tip_league: null, sport: null, in_tip: false, hint: label, demand: 1, legs: 1, unmapped: 1, fixtures };
}

const platforms: GapPlatform[] = [
  {
    id: "kalshi",
    label: "Kalshi",
    demand: 2,
    legs: 2,
    unmapped: 2,
    demand_is_sum: false,
    leagues_not_in_tip: 0,
    leagues: [league("NHL", [fixture("26SEP26ANALA", "26SEP26ANALA", "KXNHLGAME")]), league("MLB", [fixture("x", "Rays @ Phils", "YRFI")])],
  },
];

describe("gapLeaderboardTree", () => {
  it("returns everything for an empty search", () => {
    expect(searchPlatforms(platforms, " ")).toBe(platforms);
  });

  it("matches league, fixture or market names and drops emptied leagues", () => {
    expect(searchPlatforms(platforms, "nhl")[0].leagues.map((l) => l.label)).toEqual(["NHL"]);
    expect(searchPlatforms(platforms, "phils")[0].leagues.map((l) => l.label)).toEqual(["MLB"]);
    expect(searchPlatforms(platforms, "yrfi")[0].leagues.map((l) => l.label)).toEqual(["MLB"]);
    expect(searchPlatforms(platforms, "nothing")[0].leagues).toEqual([]);
  });
});
