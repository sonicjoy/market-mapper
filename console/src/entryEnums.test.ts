import { describe, expect, it } from "vitest";

import { CANONICAL_MARKET_TYPES } from "./entryEnums";

describe("CANONICAL_MARKET_TYPES", () => {
  it("is sorted A-Z so Editor can find types like player_outs", () => {
    const sorted = [...CANONICAL_MARKET_TYPES].sort((a, b) => a.localeCompare(b));
    expect([...CANONICAL_MARKET_TYPES]).toEqual(sorted);
    expect(CANONICAL_MARKET_TYPES).toContain("player_outs");
    expect(CANONICAL_MARKET_TYPES).toContain("player_rbis");
    expect(CANONICAL_MARKET_TYPES).toContain("player_stolen_bases");
  });
});

describe("TxODDS book", () => {
  it("is an alias-only book: in the alias form, never a venue column or league exchange", async () => {
    const { ALIAS_SPORTSBOOKS, SPORTSBOOKS, aliasKindFor, sportsbookLabel } = await import("./entryEnums");
    expect(ALIAS_SPORTSBOOKS).toContain("txodds");
    expect(SPORTSBOOKS as readonly string[]).not.toContain("txodds");
    expect(aliasKindFor("txodds")).toBe("external_id");
    expect(sportsbookLabel("txodds")).toBe("TxODDS");
  });
});
