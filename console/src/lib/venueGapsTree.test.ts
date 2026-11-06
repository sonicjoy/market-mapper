import { describe, expect, it } from "vitest";

import type { VenueGapFixtureDetail, VenueGapLeague, VenueGapMarket } from "../venueGapsApi";
import { arrangeLeagues, arrangeMarkets, coverageOf, MAX_SAMPLE_ROWS, nodeId, sampleRows } from "./venueGapsTree";

function league(meta: string, fixtures: Array<[string, number, number, number]>): VenueGapLeague {
  const rows = fixtures.map(([key, total, mapped, demand], i) => ({
    fixture_key: key,
    name: `${meta} game ${i}`,
    start_date: `2026-09-2${i + 5}T17:00:00+00:00`,
    ttko_hours: 10,
    total,
    mapped,
    unmapped: total - mapped,
    demand,
  }));
  const sum = (f: (r: (typeof rows)[number]) => number) => rows.reduce((acc, r) => acc + f(r), 0);
  return {
    meta_league: meta,
    sport_grouping: meta,
    tip: { status: "in_tip", league: meta.toLowerCase(), league_label: meta, sport: null, candidates: [], fix: null },
    fixtures: rows,
    total: sum((r) => r.total),
    mapped: sum((r) => r.mapped),
    unmapped: sum((r) => r.unmapped),
    demand: sum((r) => r.demand),
  };
}

function market(id: string, contract: string, selections: Array<[string, boolean]>): VenueGapMarket {
  const mapped = selections.filter(([, m]) => m).length;
  return {
    market_id: id,
    market_group: "Game Line",
    contract_type: contract,
    period_type: null,
    label: contract,
    total: selections.length,
    mapped,
    unmapped: selections.length - mapped,
    demand: 0,
    selections: selections.map(([key, m]) => ({ key, outcome: key, participant: null, mapped: m, demand: 0 })),
  };
}

function detail(markets: VenueGapMarket[]): VenueGapFixtureDetail {
  return { platform: "crypto", fixture_key: "fx", name: "A @ B", league: "nfl", sport: "football", markets, error: null };
}

describe("venueGapsTree", () => {
  it("classifies coverage", () => {
    expect(coverageOf({ total: 4, mapped: 4 })).toBe("mapped");
    expect(coverageOf({ total: 4, mapped: 1 })).toBe("partial");
    expect(coverageOf({ total: 4, mapped: 0 })).toBe("unmapped");
  });

  it("hides fully mapped fixtures and leagues when unmapped only", () => {
    const leagues = [league("NFL", [["a", 10, 10, 0], ["b", 10, 4, 0]]), league("EPL", [["c", 5, 5, 0]])];
    const out = arrangeLeagues(leagues, { sort: "unmapped", unmappedOnly: true });
    expect(out.map((l) => l.meta_league)).toEqual(["NFL"]);
    expect(out[0].fixtures.map((f) => f.fixture_key)).toEqual(["b"]);
    expect(arrangeLeagues(leagues, { sort: "unmapped", unmappedOnly: false })).toHaveLength(2);
  });

  it("sorts by demand and filters by search", () => {
    const leagues = [league("NFL", [["a", 10, 0, 1]]), league("EPL", [["c", 5, 0, 9]])];
    expect(arrangeLeagues(leagues, { sort: "demand", unmappedOnly: true }).map((l) => l.meta_league)).toEqual([
      "EPL",
      "NFL",
    ]);
    expect(arrangeLeagues(leagues, { sort: "demand", unmappedOnly: true, q: "nfl game" })).toHaveLength(1);
  });

  it("samples one unmapped selection per contract type for a fixture", () => {
    const d = detail([
      market("m1", "Moneyline", [["s1", true], ["s2", false]]),
      market("m2", "Moneyline", [["s3", false]]),
      market("m3", "Spread", [["s4", false], ["s5", false]]),
      market("m4", "Total", [["s6", true]]),
    ]);
    const rows = sampleRows({ kind: "fixture", meta: "NFL", fixtureKey: "fx" }, d);
    expect(rows.map((r) => r.key).sort()).toEqual(["s2", "s4"]);
    expect(rows[0]).toMatchObject({ league: "nfl", fixture: "A @ B", market_group: "Game Line" });
  });

  it("caps fixture samples and scopes market / selection nodes", () => {
    const many = Array.from({ length: MAX_SAMPLE_ROWS + 4 }, (_, i) => market(`m${i}`, `C${i}`, [[`s${i}`, false]]));
    expect(sampleRows({ kind: "fixture", meta: "NFL", fixtureKey: "fx" }, detail(many))).toHaveLength(MAX_SAMPLE_ROWS);
    const d = detail([market("m1", "Spread", [["a", false], ["b", false], ["c", false], ["d", false], ["e", true]])]);
    expect(sampleRows({ kind: "market", meta: "NFL", fixtureKey: "fx", marketId: "m1" }, d)).toHaveLength(3);
    const sel = { kind: "selection", meta: "NFL", fixtureKey: "fx", marketId: "m1" } as const;
    expect(sampleRows({ ...sel, key: "b" }, d).map((r) => r.key)).toEqual(["b"]);
    expect(sampleRows({ ...sel, key: "e" }, d)).toEqual([]);
    expect(sampleRows({ kind: "league", meta: "NFL" }, d)).toEqual([]);
  });

  it("gives every node kind a distinct id", () => {
    const ids = [
      nodeId({ kind: "league", meta: "NFL" }),
      nodeId({ kind: "fixture", meta: "NFL", fixtureKey: "fx" }),
      nodeId({ kind: "market", meta: "NFL", fixtureKey: "fx", marketId: "m" }),
      nodeId({ kind: "selection", meta: "NFL", fixtureKey: "fx", marketId: "m", key: "k" }),
    ];
    expect(new Set(ids).size).toBe(4);
  });

  it("keeps only picked market names in the drill-down and the fixture sample", () => {
    const d = detail([
      market("m1", "Moneyline", [["s1", false]]),
      market("m2", "Spread", [["s2", false], ["s3", false]]),
    ]);
    expect(arrangeMarkets(d.markets, true, ["spread"]).map((m) => m.market_id)).toEqual(["m2"]);
    expect(arrangeMarkets(d.markets, true, []).map((m) => m.market_id)).toEqual(["m2", "m1"]);
    const fixture = { kind: "fixture" as const, meta: "NFL", fixtureKey: "fx" };
    expect(sampleRows(fixture, d, ["Moneyline"]).map((r) => r.key)).toEqual(["s1"]);
    expect(sampleRows(fixture, d).map((r) => r.contract_type).sort()).toEqual(["Moneyline", "Spread"]);
  });
});
