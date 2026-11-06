import { describe, expect, it } from "vitest";

import type { OverridePattern } from "../overridePatternsApi";
import {
  DEFAULT_MIN_GAMES,
  canPropose,
  readOverridePatternsQuery,
  shapeLabel,
  verdictFor,
  warningFor,
  writeOverridePatternsQuery,
} from "./overridePatterns";

function pattern(over: Partial<OverridePattern> = {}): OverridePattern {
  return {
    cluster_id: "market_rule:0123456789ab",
    kind: "market_rule",
    sportsbook: "polymarket_usa",
    league: "nfl",
    optic_market_id: "1h_btts",
    source_key_type: "kind",
    source_key: "btts-1h",
    code: "",
    selection: "",
    games: 3,
    overrides: 4,
    active: 4,
    sources: ["script"],
    sample_keys: [],
    draft: { status: "draftable", detail: "" },
    proposed: false,
    ...over,
  };
}

describe("overridePatterns", () => {
  it("labels both cluster shapes", () => {
    expect(shapeLabel(pattern())).toBe("btts-1h -> 1h_btts");
    expect(shapeLabel(pattern({ kind: "alias", code: "KCC", selection: "Kansas City Chiefs" }))).toBe(
      "KCC -> Kansas City Chiefs",
    );
  });

  it("only offers Propose for draftable clusters not already on Proposed", () => {
    expect(canPropose(pattern())).toBe(true);
    expect(canPropose(pattern({ proposed: true }))).toBe(false);
    expect(canPropose(pattern({ draft: { status: "already_mapped", detail: "" } }))).toBe(false);
  });

  it("maps kernel verdicts to tones and passes unknown codes through", () => {
    expect(verdictFor("already_ignored").tone).toBe("stop");
    expect(verdictFor("draftable").tone).toBe("go");
    expect(verdictFor("brand_new_reason")).toEqual({ text: "brand_new_reason", tone: "warn" });
  });

  it("round-trips URL state and drops defaults", () => {
    const params = writeOverridePatternsQuery(new URLSearchParams(), { kind: "alias", minGames: 5, includeInactive: true });
    expect(params.toString()).toBe("kind=alias&min_games=5&inactive=1");
    expect(readOverridePatternsQuery(params)).toEqual({ kind: "alias", minGames: 5, includeInactive: true });
    expect(readOverridePatternsQuery(new URLSearchParams("kind=bogus&min_games=0"))).toEqual({
      kind: "",
      minGames: DEFAULT_MIN_GAMES,
      includeInactive: false,
    });
  });

  it("never lets a refused pattern be proposed, and explains why", () => {
    const refused = pattern({ draft: { status: "no_optic_canonical", detail: "" } });
    expect(canPropose(refused)).toBe(false);
    const warning = warningFor(refused);
    expect(warning?.title).toMatch(/no rule will be proposed/i);
    expect(warning?.why).toMatch(/league-wide/);
    expect(warningFor(pattern({ draft: { status: "already_ignored", detail: "" } }))?.title).toMatch(/Conflict/);
    expect(warningFor(pattern())).toBeNull();
  });
});
