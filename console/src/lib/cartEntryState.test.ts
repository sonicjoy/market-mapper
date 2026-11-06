import { describe, expect, it } from "vitest";

import { cartItemToEntryState } from "./cartEntryState";

describe("cartItemToEntryState", () => {
  it("opens Mapper league tab with the cart payload", () => {
    const state = cartItemToEntryState({
      id: "cart_val",
      kind: "mapping_league",
      label: "League valorant",
      payload: {
        league: "valorant",
        sport: "esports",
        optic_league_id: "",
        fixture_source: "api",
        notes: "From Mapper Chat",
        exchanges: [
          { sportsbook: "px", enabled: true, parser_profile: "px_generic_v1" },
          { sportsbook: "optic", enabled: true, parser_profile: "optic_standard_v1" },
        ],
      },
    });
    expect(state.tab).toBe("league");
    expect(state.cartItemId).toBe("cart_val");
    expect(state.league).toBe("valorant");
    expect(state.sport).toBe("esports");
    expect(state.optic_league_id).toBe("");
    expect(state.exchanges).toHaveLength(2);
    expect(state.note).toBe("From Mapper Chat");
  });

  it("opens the market tab with official text and trader notes", () => {
    const state = cartItemToEntryState({
      id: "cart_rof",
      kind: "mapping_market_rules",
      label: "ufc rof",
      payload: {
        kind: "mapping_market_rules",
        league: "ufc",
        rules: [
          {
            sportsbook: "polymarket_usa",
            source_key: "rof-before-r",
            source_key_type: "ticker_suffix",
            action: "ignore",
            official_description: "Fight ends before Round N begins",
            citation_url: "https://example.invalid/rules",
            notes: "not Optic total_rounds",
          },
        ],
      },
    });
    expect(state.tab).toBe("market");
    expect(state.source_key).toBe("rof-before-r");
    expect(state.official_description).toBe("Fight ends before Round N begins");
    expect(state.citation_url).toBe("https://example.invalid/rules");
    expect(state.note).toBe("not Optic total_rounds");
  });

  it("keeps line, side, and match operator on the market tab", () => {
    const state = cartItemToEntryState({
      id: "cart_rounds",
      kind: "mapping_market_rules",
      label: "ufc rounds",
      payload: {
        league: "ufc",
        rules: [
          {
            sportsbook: "polymarket_usa",
            source_key: "rof-before-r",
            source_key_type: "ticker_suffix",
            action: "map",
            canonical_market_type: "total_rounds",
            match_operator: "prefix",
            line_offset: -0.5,
            yes_side: "under",
            side_swap: false,
          },
        ],
      },
    });
    expect(state.line_offset).toBe(-0.5);
    expect(state.yes_side).toBe("under");
    expect(state.side_swap).toBe(false);
    expect(state.match_operator).toBe("prefix");
  });
});
