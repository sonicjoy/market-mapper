import { describe, expect, it } from "vitest";

import { bookChipClass, bookChipTitle, leagueBookSlots } from "./leagueBooks";

describe("leagueBookSlots", () => {
  it("fills expected books that are absent from the league row", () => {
    const slots = leagueBookSlots([
      { sportsbook: "optic", enabled: true, source_league_id: "atp" },
      { sportsbook: "px", enabled: false },
    ]);
    const byBook = Object.fromEntries(slots.map((s) => [s.sportsbook, s]));
    expect(byBook.optic).toEqual({
      sportsbook: "optic",
      present: true,
      enabled: true,
      source_league_id: "atp",
    });
    expect(byBook.px).toMatchObject({ present: true, enabled: false });
    expect(byBook.kalshi).toBeUndefined();
    expect(byBook["crypto.com"]).toMatchObject({ present: false, enabled: false });
    expect(byBook.novig).toMatchObject({ present: false });
  });

  it("keeps unknown extra sportsbooks after the known set", () => {
    const slots = leagueBookSlots([{ sportsbook: "otherbook", enabled: true }]);
    expect(slots.at(-1)).toMatchObject({ sportsbook: "otherbook", present: true, enabled: true });
  });
});

describe("bookChipClass", () => {
  it("uses brand, strikethrough, and dashed states", () => {
    expect(bookChipClass({ present: true, enabled: true })).toContain("bg-brand-50");
    expect(bookChipClass({ present: true, enabled: false })).toContain("line-through");
    expect(bookChipClass({ present: false, enabled: false })).toContain("border-dashed");
  });
});

describe("bookChipTitle", () => {
  it("explains a sportsbook missing from the league", () => {
    expect(bookChipTitle({ sportsbook: "px", present: false, enabled: false })).toContain(
      "Not on this league",
    );
  });

  it("explains a disabled pin with no source id", () => {
    expect(
      bookChipTitle({ sportsbook: "novig", present: true, enabled: false }),
    ).toContain("Novig league string");
  });
});
