import { describe, expect, it } from "vitest";

import {
  approveCount,
  defaultKeep,
  dropsForApprove,
  fixtureRfqVolume,
  formatOpticTtko,
  formatRailMeta,
  formatTtko,
  leaguePillLabel,
  otherLeagueScope,
  parseKindFilter,
  pickVisibleLeague,
  rowsForKind,
  rowsForSelection,
  rowsHidingOptic,
  showsFixtures,
  visibleLeaguePills,
} from "./proposedRail";
import type { MappingRow, ProposedLeagueBlock } from "../types";

const aliasRow = (overrides: Partial<MappingRow> = {}): MappingRow => ({
  kind: "alias",
  key: "alias:epl:ARS:kalshi:ARS",
  action: "add",
  tier: "confirmed",
  confidence: null,
  reason: null,
  alternatives: [],
  keep_default: true,
  league: "epl",
  league_label: "EPL",
  league_is_new: false,
  sport: "soccer",
  rfq_demand: null,
  next_fixtures: [{ fixture_id: "fx1", label: "Arsenal vs Chelsea" }],
  evidence: [],
  source: { platform: "Kalshi", name: "Arsenal", code: "ARS" },
  target: { platform: "Optic", name: "Arsenal", code: "ARS" },
  ...overrides,
});

describe("proposedRail", () => {
  it("defaults guess rows to drop", () => {
    const row = aliasRow({ tier: "guess", keep_default: false });
    expect(defaultKeep(row, new Set())).toBe(false);
    expect(defaultKeep(row, new Set(["alias:epl:ARS:kalshi:ARS"]))).toBe(true);
  });

  it("defaults ai suggestion rows to keep when keep_default is true", () => {
    const row = aliasRow({ tier: "ai", keep_default: true });
    expect(defaultKeep(row, new Set())).toBe(true);
    expect(defaultKeep(row, new Set([`drop:${row.key}`]))).toBe(false);
  });

  it("defaults confirmed rows with AI evidence from keep_default", () => {
    const row = aliasRow({
      evidence: [
        "ai:suggest",
        "AI suggestion — unique-bind did not apply; human must Approve.",
      ],
    });
    expect(defaultKeep(row, new Set())).toBe(true);
    expect(defaultKeep(row, new Set([`drop:${row.key}`]))).toBe(false);
  });

  it("explicit drop overrides confirmed keep_default", () => {
    const row = aliasRow();
    const dropped = new Set([`drop:${row.key}`]);
    expect(defaultKeep(row, dropped)).toBe(false);
    expect(dropsForApprove([row], dropped)).toEqual([{ kind: "alias", key: row.key }]);
  });

  it("filters alias rows by next_fixtures fixture id", () => {
    const block: ProposedLeagueBlock = {
      league: "epl",
      league_label: "EPL",
      sport: "soccer",
      is_new: false,
      fixtures: [{ fixture_id: "fx1", label: "Arsenal vs Chelsea" }],
      rows: [
        aliasRow(),
        aliasRow({
          key: "alias:epl:LIV:kalshi:LIV",
          target: { platform: "Optic", name: "Liverpool", code: "LIV" },
          next_fixtures: [],
        }),
      ],
    };
    const rows = rowsForSelection(block, { type: "fixture", league: "epl", fixtureId: "fx1" });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.target.name).toBe("Arsenal");
  });

  it("league header shows all pins for the league", () => {
    const block: ProposedLeagueBlock = {
      league: "epl",
      league_label: "EPL",
      sport: "soccer",
      is_new: false,
      fixtures: [{ fixture_id: "fx1", label: "Arsenal vs Chelsea" }],
      rows: [
        aliasRow(),
        aliasRow({
          kind: "market_rule",
          key: "rule:epl:polymarket:kind:moneyline",
          next_fixtures: [],
        }),
      ],
    };
    const rows = rowsForSelection(block, { type: "league", league: "epl" });
    expect(rows.map((r) => r.kind)).toEqual(["alias", "market_rule"]);
  });

  it("kind filter isolates market-rule rows including cloned pins", () => {
    const alias = aliasRow();
    const league = aliasRow({
      kind: "league",
      key: "league:austria_ofb_cup",
      league: "austria_ofb_cup",
      clone_from: "epl",
    });
    const cloned = aliasRow({
      kind: "market_rule",
      key: "rule:austria_ofb_cup:polymarket:kind:totals",
      league: "austria_ofb_cup",
      clone_from: "epl",
    });
    const rows = [alias, league, cloned];
    expect(rowsForKind(rows, "all")).toEqual(rows);
    expect(rowsForKind(rows, "alias")).toEqual([alias]);
    expect(rowsForKind(rows, "league")).toEqual([league]);
    expect(rowsForKind(rows, "market_rule")).toEqual([cloned]);
    expect(parseKindFilter("ai")).toBe("ai");
    expect(parseKindFilter("nope")).toBe("all");
  });

  it("kind filter isolates AI guess rows from confirmed aliases", () => {
    const confirmed = aliasRow();
    const ai = aliasRow({ key: "alias:epl:AI:kalshi:AI", tier: "ai", keep_default: true });
    const guess = aliasRow({
      key: "alias:epl:G:kalshi:G",
      tier: "guess",
      keep_default: false,
    });
    const noted = aliasRow({
      key: "alias:epl:N:kalshi:N",
      evidence: ["AI suggestion — unique-bind did not apply; human must Approve."],
    });
    const rows = [confirmed, ai, guess, noted];
    expect(rowsForKind(rows, "ai")).toEqual([ai, guess, noted]);
    expect(rowsForKind(rows, "alias")).toEqual(rows);
    expect(showsFixtures("ai")).toBe(true);
    expect(showsFixtures("market_rule")).toBe(false);
  });

  it("kind filter isolates rows proposed from override patterns", () => {
    const plain = aliasRow();
    const fromPattern = aliasRow({
      key: "alias:nfl:KC:kalshi:KCC",
      evidence: ["note:override_cluster:alias:0123456789ab", "kalshi:override:KXNFLGAME-26SEP20KCCBUF-KCC|yes"],
    });
    expect(rowsForKind([plain, fromPattern], "override")).toEqual([fromPattern]);
    expect(parseKindFilter("override")).toBe("override");
  });

  it("league header uses allRows when block.rows is empty", () => {
    const pin = aliasRow();
    const block: ProposedLeagueBlock = {
      league: "epl",
      league_label: "EPL",
      sport: "soccer",
      is_new: false,
      fixtures: [{ fixture_id: "fx1", label: "Arsenal vs Chelsea" }],
      rows: [],
    };
    const rows = rowsForSelection(block, { type: "league", league: "epl" }, [pin]);
    expect(rows).toEqual([pin]);
  });

  it("fixture filter matches alias by team name when next_fixtures is empty", () => {
    const block: ProposedLeagueBlock = {
      league: "cs2",
      league_label: "Cs2",
      sport: "cs2",
      is_new: false,
      fixtures: [{ fixture_id: "fx9", label: "ENRAGE vs Drama eSports" }],
      rows: [
        aliasRow({
          league: "cs2",
          league_label: "Cs2",
          next_fixtures: [],
          target: { platform: "Optic", name: "ENRAGE", code: "ENR" },
        }),
      ],
    };
    const rows = rowsForSelection(block, { type: "fixture", league: "cs2", fixtureId: "fx9" });
    expect(rows).toHaveLength(1);
  });

  it("approve count keeps ai guesses by default", () => {
    const rows = [
      aliasRow(),
      aliasRow({ tier: "ai", keep_default: true, key: "g1" }),
      aliasRow({ tier: "guess", keep_default: false, key: "g2" }),
    ];
    expect(approveCount(rows, new Set())).toBe(2);
    expect(dropsForApprove(rows, new Set())).toEqual([{ kind: "alias", key: "g2" }]);
  });

  it("names other-league approve scope", () => {
    const rows = [
      aliasRow(),
      aliasRow({ league: "nba", league_label: "NBA", key: "nba-1" }),
    ];
    expect(otherLeagueScope(rows, "epl", new Set())).toContain("1 items in 1 other league");
  });

  it("hides Optic-to-Optic alias rows when asked", () => {
    const optic = aliasRow({
      key: "alias:atp:DSA5:optic:4E10",
      sportsbook: "optic",
      source: { platform: "Optic", name: "Dane Sweeny", code: "4E10" },
      target: { platform: "Optic", name: "Dane Sweeny", code: "DSA5" },
    });
    const kalshi = aliasRow();
    expect(rowsHidingOptic([optic, kalshi], false)).toEqual([optic, kalshi]);
    expect(rowsHidingOptic([optic, kalshi], true)).toEqual([kalshi]);
  });

  it("hidden optic ai rows still approve when default keep", () => {
    const opticAi = aliasRow({
      key: "alias:atp:DSA5:optic:4E10",
      tier: "ai",
      keep_default: true,
      sportsbook: "optic",
      source: { platform: "Optic", name: "Dane Sweeny", code: "4E10" },
      target: { platform: "Optic", name: "Dane Sweeny", code: "DSA5" },
    });
    expect(rowsHidingOptic([opticAi], true)).toEqual([]);
    expect(defaultKeep(opticAi, new Set())).toBe(true);
    expect(approveCount([opticAi], new Set())).toBe(1);
  });

  it("shows pin counts on league pills including All", () => {
    expect(leaguePillLabel("Atp", 4)).toBe("Atp · 4");
    expect(leaguePillLabel("Azerbaijan 1st Division", 1, true)).toBe(
      "Azerbaijan 1st Division · new · 1",
    );
  });

  it("omits league pills that have no rows after Hide Optic", () => {
    const optic = aliasRow({
      key: "alias:itf_women:IVA:optic:IVA",
      league: "itf_women",
      league_label: "Itf Women",
      sportsbook: "optic",
      source: { platform: "Optic", name: "Iva Marinkovic", code: "IVA" },
      target: { platform: "Optic", name: "Iva Marinkovic", code: "IVA" },
    });
    const kalshi = aliasRow({ league: "epl", league_label: "EPL" });
    const leagues = [
      { league: "epl", league_label: "EPL", is_new: false },
      { league: "itf_women", league_label: "Itf Women", is_new: false },
    ];
    expect(visibleLeaguePills(leagues, [optic, kalshi], "all", false)).toEqual([
      { id: "epl", label: "EPL · 1" },
      { id: "itf_women", label: "Itf Women · 1" },
    ]);
    expect(visibleLeaguePills(leagues, [optic, kalshi], "all", true)).toEqual([
      { id: "epl", label: "EPL · 1" },
    ]);
    expect(pickVisibleLeague([{ id: "epl" }], "itf_women")).toBe("epl");
    expect(pickVisibleLeague([], "itf_women")).toBe("itf_women");
  });

  it("omits league pills that have no rows for the kind filter", () => {
    const alias = aliasRow();
    const rule = aliasRow({
      kind: "market_rule",
      key: "rule:itf_women:polymarket:kind:moneyline",
      league: "itf_women",
      league_label: "Itf Women",
    });
    const leagues = [
      { league: "epl", league_label: "EPL", is_new: false },
      { league: "itf_women", league_label: "Itf Women", is_new: false },
    ];
    expect(visibleLeaguePills(leagues, [alias, rule], "alias", false)).toEqual([
      { id: "epl", label: "EPL · 1" },
    ]);
  });

  it("formats hours, rfq volume, and pin count", () => {
    expect(formatRailMeta(6, 12, 4)).toBe("6h · 12 RFQ · 4 pins");
    expect(formatRailMeta(6, 0, 4)).toBe("6h · 4 pins");
    expect(formatRailMeta(6, null, 1)).toBe("6h · 1 pin");
    expect(formatRailMeta(-2, 12, 4)).toBe("-2h · 12 RFQ · 4 pins");
  });

  it("formats signed ttko and never says started", () => {
    expect(formatTtko(6)).toBe("6h");
    expect(formatTtko(0.4)).toBe("24m");
    expect(formatTtko(72)).toBe("3d");
    expect(formatTtko(-2)).toBe("-2h");
    expect(formatTtko(-0.5)).toBe("-30m");
    expect(formatTtko(-60)).toBe("-3d");
    expect(formatTtko(null)).toBe("TBD");
    expect(formatTtko(-2)).not.toContain("started");
  });

  it("joins optic status with signed ttko for live and pre", () => {
    expect(formatOpticTtko("delayed", -2)).toBe("delayed · -2h");
    expect(formatOpticTtko("unplayed", 12)).toBe("unplayed · 12h");
    expect(formatOpticTtko("live", 0.5)).toBe("live · 30m");
    expect(formatOpticTtko("live", -1)).toBe("live · -1h");
    expect(formatOpticTtko("unplayed", -0.25)).toBe("unplayed · -15m");
    expect(formatOpticTtko("", -2)).toBe("-2h");
    expect(formatOpticTtko("delayed", null)).toBe("delayed");
    expect(formatOpticTtko("delayed", -2)).not.toContain("started");
  });

  it("prefers fixture rfq_demand over related rows", () => {
    const fx = { fixture_id: "fx1", label: "A vs B", rfq_demand: 20 };
    const related = [aliasRow({ rfq_demand: 12 }), aliasRow({ rfq_demand: 8, key: "b" })];
    expect(fixtureRfqVolume(fx, related)).toBe(20);
  });

  it("falls back to max related-row rfq_demand", () => {
    const fx = { fixture_id: "fx1", label: "A vs B" };
    expect(
      fixtureRfqVolume(fx, [aliasRow({ rfq_demand: 12 }), aliasRow({ rfq_demand: 8, key: "b" })]),
    ).toBe(12);
  });
});
