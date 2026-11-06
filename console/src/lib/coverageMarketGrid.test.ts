import { describe, expect, it } from "vitest";

import { SPORTSBOOKS } from "../entryEnums";
import {
  baselineToggles,
  cellHasRule,
  cellSourceLabel,
  coverageCellKey,
  coverageGridAxes,
  coveragePlatformLabel,
  dirtyToggleKeys,
  coverageLeagueHeaderState,
  leaguePlatformEntryState,
  missingMarketEntryState,
  normalizeCoverageSportsbook,
  platformLeagueEnabled,
  publishedMappedKeys,
  rowsForToggleChanges,
} from "./coverageMarketGrid";
import type { MarketRuleRow } from "../types";

function rule(patch: Partial<MarketRuleRow> & Pick<MarketRuleRow, "sportsbook" | "canonical_market_type" | "action">): MarketRuleRow {
  return {
    league: "atp",
    league_label: "ATP",
    sportsbook_label: patch.sportsbook,
    rule_kind: "taxonomy",
    source_key_type: "kind",
    source_key: patch.source_key ?? "moneyline",
    priority: 100,
    enabled: true,
    ...patch,
  };
}

describe("normalizeCoverageSportsbook", () => {
  it("maps published BQ names to grid ids", () => {
    expect(normalizeCoverageSportsbook("Prophet X")).toBe("px");
    expect(normalizeCoverageSportsbook("Polymarket (USA)")).toBe("polymarket_usa");
    expect(normalizeCoverageSportsbook("Novig")).toBe("novig");
    expect(normalizeCoverageSportsbook("Underdog")).toBe("underdog");
  });
});

describe("coverageCellKey", () => {
  it("normalizes sportsbook before keying", () => {
    expect(coverageCellKey("Prophet X", "moneyline")).toBe(coverageCellKey("px", "moneyline"));
  });
});

describe("coverageGridAxes", () => {
  it("orders platforms with optic first, then SPORTSBOOKS, then extras", () => {
    const { platforms, markets } = coverageGridAxes(
      [
        rule({ sportsbook: "optic", canonical_market_type: "moneyline", action: "map" }),
        rule({ sportsbook: "polymarket", canonical_market_type: "1st_set_winner", action: "map" }),
        rule({ sportsbook: "zz-book", canonical_market_type: "moneyline", action: "map" }),
      ],
      ["1st_set_winner"],
    );
    expect(platforms[0]).toBe("optic");
    expect(platforms[1]).toBe("crypto.com");
    expect(platforms).toContain("polymarket");
    expect(platforms).not.toContain("kalshi");
    expect(platforms.at(-1)).toBe("zz-book");
    expect(markets[0]).toBe("1st_set_winner");
    expect(markets).toContain("moneyline");
  });

  it("always includes every SPORTSBOOKS column even with no rules", () => {
    const { platforms } = coverageGridAxes([]);
    for (const book of SPORTSBOOKS) {
      expect(platforms).toContain(book);
    }
  });
});

describe("missingMarketEntryState", () => {
  it("prefills Editor Amend without a source key", () => {
    const state = missingMarketEntryState({
      league: "mlb",
      sportsbook: "polymarket",
      canonical: "f3_moneyline_3way",
    });
    expect(state.tab).toBe("market");
    expect(state.mode).toBe("amend");
    expect(state.source_key).toBeUndefined();
    expect(state.canonical_market_type).toBe("f3_moneyline_3way");
    expect(state.source_key_type).toBe("kind");
  });

  it("uses market_type for novig", () => {
    const state = missingMarketEntryState({
      league: "nba",
      sportsbook: "novig",
      canonical: "moneyline",
    });
    expect(state.source_key_type).toBe("market_type");
  });

  it("uses udx_ticker for underdog", () => {
    const state = missingMarketEntryState({
      league: "nfl",
      sportsbook: "underdog",
      canonical: "moneyline",
    });
    expect(state.source_key_type).toBe("udx_ticker");
  });
});

describe("publishedMappedKeys", () => {
  it("keys stamped book×canonical cells", () => {
    const keys = publishedMappedKeys([
      {
        sportsbook: "Kalshi",
        sportsbook_label: "Kalshi",
        mapped_count: 1,
        expected_count: 2,
        markets: [
          { canonical_market_type: "moneyline", mapped: true },
          { canonical_market_type: "game_total", mapped: false },
        ],
      },
    ]);
    expect(keys.has(coverageCellKey("kalshi", "moneyline"))).toBe(true);
    expect(keys.has(coverageCellKey("kalshi", "game_total"))).toBe(false);
  });

  it("normalizes Prophet X to px", () => {
    const keys = publishedMappedKeys([
      {
        sportsbook: "Prophet X",
        sportsbook_label: "ProphetX",
        mapped_count: 1,
        expected_count: 1,
        markets: [{ canonical_market_type: "moneyline", mapped: true }],
      },
    ]);
    expect(keys.has(coverageCellKey("px", "moneyline"))).toBe(true);
  });
});

describe("platformLeagueEnabled", () => {
  const base = {
    sport: "tennis",
    optic_league_id: "atp",
    fixture_source: "api",
    fixture_horizon_hours: 168,
    enabled: true,
    exchanges: [],
  };

  it("requires optic_league_id for optic", () => {
    expect(platformLeagueEnabled(base, "optic")).toBe(true);
    expect(platformLeagueEnabled({ ...base, optic_league_id: "" }, "optic")).toBe(false);
  });

  it("falls back from empty settings.league to source_league_id for novig", () => {
    expect(
      platformLeagueEnabled(
        {
          ...base,
          exchanges: [
            {
              sportsbook: "novig",
              enabled: true,
              source_league_id: "ATP",
              settings: { league: "" },
            },
          ],
        },
        "novig",
      ),
    ).toBe(true);
  });

  it("falls back from empty settings.slug_prefix to source_league_id for polymarket_usa", () => {
    expect(
      platformLeagueEnabled(
        {
          ...base,
          exchanges: [
            {
              sportsbook: "polymarket_usa",
              enabled: true,
              source_league_id: "mlb",
              settings: { slug_prefix: "" },
            },
          ],
        },
        "polymarket_usa",
      ),
    ).toBe(true);
  });
});

describe("coveragePlatformLabel", () => {
  it("uses console labels for grid ids", () => {
    expect(coveragePlatformLabel("novig")).toBe("Novig");
    expect(coveragePlatformLabel("px")).toBe("ProphetX");
    expect(coveragePlatformLabel("Prophet X")).toBe("ProphetX");
    expect(coveragePlatformLabel("polymarket_usa")).toBe("Polymarket US");
  });
});

describe("coverageLeagueHeaderState", () => {
  it("opens league tab with focus when league_detail is missing", () => {
    const state = coverageLeagueHeaderState("mlb", "novig", "baseball");
    expect(state.tab).toBe("league");
    expect(state.league).toBe("mlb");
    expect(state.sport).toBe("baseball");
    expect(state.focusSportsbook).toBe("novig");
    expect(state.exchanges).toBeUndefined();
  });
});

describe("leaguePlatformEntryState", () => {
  it("prefills league tab with focus book", () => {
    const state = leaguePlatformEntryState("mlb", {
      sport: "baseball",
      optic_league_id: "mlb",
      fixture_source: "api",
      fixture_horizon_hours: 96,
      enabled: true,
      entity_type: "team",
      alias_enforcement: "warn",
      runshop_enabled: true,
      exchanges: [],
    }, "novig");
    expect(state.tab).toBe("league");
    expect(state.focusSportsbook).toBe("novig");
    expect(state.fixture_horizon_hours).toBe(96);
    expect(state.entity_type).toBe("team");
    expect(state.alias_enforcement).toBe("warn");
    expect(state.runshop_enabled).toBe(true);
  });
});

describe("cellHasRule", () => {
  it("is false when that book has no canonical pin", () => {
    const rules = [rule({ sportsbook: "polymarket", canonical_market_type: "moneyline", action: "map" })];
    expect(cellHasRule(rules, "polymarket", "moneyline")).toBe(true);
    expect(cellHasRule(rules, "optic", "moneyline")).toBe(false);
    expect(baselineToggles(rules)[coverageCellKey("optic", "moneyline")]).toBeUndefined();
  });

  it("labels the cell with the platform source key", () => {
    const rules = [
      rule({ sportsbook: "polymarket", canonical_market_type: "moneyline", action: "map", source_key: "match-winner" }),
      rule({ sportsbook: "optic", canonical_market_type: "moneyline", action: "map", source_key: "moneyline" }),
    ];
    expect(cellSourceLabel(rules, "polymarket", "moneyline")).toBe("match-winner");
    expect(cellSourceLabel(rules, "optic", "moneyline")).toBe("moneyline");
    expect(cellSourceLabel(rules, "crypto.com", "moneyline")).toBe("");
  });
});

describe("toggle dirty rows", () => {
  const rules = [
    rule({ sportsbook: "polymarket", canonical_market_type: "moneyline", action: "map", source_key: "match-winner" }),
    rule({ sportsbook: "optic", canonical_market_type: "moneyline", action: "ignore", source_key: "ml" }),
  ];

  it("stages disable when an On cell is turned Off", () => {
    const baseline = baselineToggles(rules);
    const key = coverageCellKey("polymarket", "moneyline");
    expect(baseline[key]).toBe(true);
    const toggles = { ...baseline, [key]: false };
    expect(dirtyToggleKeys(baseline, toggles)).toEqual([key]);
    const { enableRows, disableRows } = rowsForToggleChanges(rules, baseline, toggles);
    expect(enableRows).toHaveLength(0);
    expect(disableRows.map((row) => row.source_key)).toEqual(["match-winner"]);
  });
});
