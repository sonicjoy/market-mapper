import { describe, expect, it } from "vitest";

import { fillMarketPrefill, proposedEditState } from "./proposedEditState";
import type { MappingRow } from "../types";

const base = (overrides: Partial<MappingRow> = {}): MappingRow => ({
  kind: "market_rule",
  key: "rule:austria_ofb_cup:crypto.com:contract_type:To Advance",
  action: "add",
  tier: "confirmed",
  confidence: null,
  reason: null,
  alternatives: [],
  keep_default: true,
  league: "austria_ofb_cup",
  league_label: "Austria Ofb Cup",
  league_is_new: true,
  sport: "soccer",
  sportsbook: "crypto.com",
  rfq_demand: null,
  next_fixtures: [],
  evidence: [],
  source: {
    platform: "crypto.com",
    name: "To Advance",
    code: "To Advance",
    description: "contract_type",
  },
  target: {
    platform: "Optic",
    name: "to_advance",
    description: "to_advance",
  },
  ...overrides,
});

describe("proposedEditState", () => {
  it("prefills canonical market type for a mapped rule", () => {
    const state = proposedEditState(base());
    expect(state.tab).toBe("market");
    expect(state.mode).toBe("amend");
    expect(state.league).toBe("austria_ofb_cup");
    expect(state.sportsbook).toBe("crypto.com");
    expect(state.source_key).toBe("To Advance");
    expect(state.source_key_type).toBe("contract_type");
    expect(state.action).toBe("map");
    expect(state.canonical_market_type).toBe("to_advance");
  });

  it("prefills official text and trader notes apart from each other", () => {
    const state = proposedEditState(
      base({
        official_description: "Fight ends before Round N begins",
        citation_url: "https://example.invalid/rules",
        notes: "not Optic total_rounds",
      }),
    );
    expect(state.official_description).toBe("Fight ends before Round N begins");
    expect(state.citation_url).toBe("https://example.invalid/rules");
    expect(state.note).toBe("not Optic total_rounds");
  });

  it("prefills line, side, and match operator", () => {
    const state = proposedEditState(
      base({
        line_offset: -0.5,
        yes_side: "under",
        side_swap: false,
        match_operator: "prefix",
      }),
    );
    expect(state.line_offset).toBe(-0.5);
    expect(state.yes_side).toBe("under");
    expect(state.side_swap).toBe(false);
    expect(state.match_operator).toBe("prefix");
  });

  it("prefills ignore without a canonical type", () => {
    const state = proposedEditState(
      base({
        target: { platform: "Optic", name: "ignored", description: "ignore" },
      }),
    );
    expect(state.action).toBe("ignore");
    expect(state.canonical_market_type).toBeNull();
  });

  it("uses target description when name is blank", () => {
    const state = proposedEditState(
      base({
        target: { platform: "Optic", name: "", description: "to_advance" },
      }),
    );
    expect(state.action).toBe("map");
    expect(state.canonical_market_type).toBe("to_advance");
  });

  it("does not attach market fields to alias cards", () => {
    const state = proposedEditState(
      base({
        kind: "alias",
        key: "alias:epl:ARS:px:ARS",
        sportsbook: "px",
        source: { platform: "ProphetX", name: "Arsenal", code: "ARS" },
        target: { platform: "Optic", name: "Arsenal", code: "ARS" },
      }),
    );
    expect(state.tab).toBe("alias");
    expect(state.canonical_market_type).toBeUndefined();
    expect(state.source_key).toBeUndefined();
  });

  it("carries the Proposed return path for Edit", () => {
    const state = proposedEditState(
      base(),
      "/review/P_abc?league=austria_ofb_cup&kind=market_rule",
    );
    expect(state.returnTo).toBe("/review/P_abc?league=austria_ofb_cup&kind=market_rule");
  });

  it("prefills league tab from a proposed league card", () => {
    const state = proposedEditState({
      ...base({
        kind: "league",
        key: "league:nfl",
        sport: "football",
        optic_league_id: "nfl",
        fixture_source: "api",
        fixture_horizon_hours: 168,
        enabled: true,
        exchanges: [
          {
            sportsbook: "novig",
            enabled: true,
            source_league_id: null,
            settings: { league: "NFL" },
          },
        ],
        source: { platform: "Platforms", name: "Novig (NFL)" },
        target: { platform: "Optic", name: "NFL", id: "nfl" },
      }),
    });
    expect(state.tab).toBe("league");
    expect(state.sport).toBe("football");
    expect(state.optic_league_id).toBe("nfl");
    expect(state.fixture_horizon_hours).toBe(168);
    expect(state.exchanges).toHaveLength(1);
  });
});

describe("fillMarketPrefill", () => {
  it("lifts alias-shaped Mapper Chat fields onto the market dropdown", () => {
    const state = fillMarketPrefill({
      tab: "market",
      league: "austria_ofb_cup",
      sportsbook: "crypto.com",
      code: "To Advance",
      entity_name: "to_advance",
    });
    expect(state.source_key).toBe("To Advance");
    expect(state.action).toBe("map");
    expect(state.canonical_market_type).toBe("to_advance");
  });
});
