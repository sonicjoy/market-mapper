import { describe, expect, it } from "vitest";

import { booksFromExchanges, exchangePayload } from "./leagueEntryBooks";

describe("booksFromExchanges", () => {
  it("shows Novig league from settings when source_league_id is empty", () => {
    const books = booksFromExchanges([
      {
        sportsbook: "novig",
        enabled: true,
        parser_profile: "novig_generic_v1",
        source_league_id: null,
        settings: { league: "NFL" },
      },
    ]);
    expect(books.novig.source_league_id).toBe("NFL");
  });

  it("has no Kalshi slot: Kalshi is not a tip league pin", () => {
    expect(booksFromExchanges([]).kalshi).toBeUndefined();
  });
});

describe("exchangePayload", () => {
  it("writes Novig league into settings on submit", () => {
    const body = exchangePayload("novig", {
      enabled: true,
      source_league_id: "NFL",
      parser_profile: "novig_generic_v1",
      settings: {},
    });
    expect(body.source_league_id).toBe("NFL");
    expect(body.settings).toEqual({ league: "NFL" });
  });

  it("clears Polymarket slug_prefix when source id is blank", () => {
    const body = exchangePayload("polymarket", {
      enabled: true,
      source_league_id: "",
      parser_profile: "poly_generic_v1",
      settings: { slug_prefix: "epl" },
    });
    expect(body.settings).toEqual({});
  });

  it("clears Novig league setting when source id is blank", () => {
    const body = exchangePayload("novig", {
      enabled: true,
      source_league_id: "",
      parser_profile: "novig_generic_v1",
      settings: { league: "nfl" },
    });
    expect(body.settings).toEqual({});
  });

  it("uppercases Underdog venue league in settings on submit", () => {
    const body = exchangePayload("underdog", {
      enabled: true,
      source_league_id: "nfl",
      parser_profile: "underdog_generic_v1",
      settings: {},
    });
    expect(body.source_league_id).toBe("NFL");
    expect(body.settings).toEqual({ league: "NFL" });
  });
});
