import { describe, expect, it } from "vitest";

import {
  filterStampSections,
  groupStampsByCanonical,
  nextStampInspectState,
  stampBookSummary,
  stampCountsByCell,
  stampCellKey,
} from "./coverageStamps";
import type { CoverageStampRow } from "../types";

function stamp(patch: Partial<CoverageStampRow> & Pick<CoverageStampRow, "sportsbook" | "market_type">): CoverageStampRow {
  return {
    market_id: patch.market_id ?? patch.market_type,
    entity: patch.entity ?? "SEA",
    line: patch.line ?? "—",
    side: patch.side ?? "yes",
    source_id: patch.source_id ?? "KX-SEA",
    ...patch,
  };
}

describe("stampCountsByCell", () => {
  it("counts rows per book×canonical", () => {
    const counts = stampCountsByCell([
      stamp({ sportsbook: "kalshi", market_type: "moneyline" }),
      stamp({ sportsbook: "kalshi", market_type: "moneyline", entity: "NE" }),
      stamp({ sportsbook: "crypto.com", market_type: "moneyline" }),
    ]);
    expect(counts.get(stampCellKey("kalshi", "moneyline"))).toBe(2);
    expect(counts.get(stampCellKey("crypto.com", "moneyline"))).toBe(1);
  });

  it("normalizes Prophet X stamps to px keys", () => {
    const counts = stampCountsByCell([
      stamp({ sportsbook: "Prophet X", market_type: "moneyline" }),
    ]);
    expect(counts.get(stampCellKey("px", "moneyline"))).toBe(1);
  });
});

describe("groupStampsByCanonical", () => {
  it("keeps canonical order and summarizes books", () => {
    const sections = groupStampsByCanonical(
      [
        stamp({ sportsbook: "kalshi", market_type: "game_total" }),
        stamp({ sportsbook: "kalshi", market_type: "moneyline" }),
        stamp({ sportsbook: "crypto.com", market_type: "moneyline" }),
      ],
      ["moneyline", "game_total"],
    );
    expect(sections.map((row) => row.canonical)).toEqual(["moneyline", "game_total"]);
    expect(sections[0]?.rows).toHaveLength(2);
    expect(stampBookSummary(sections[0]?.bookCounts ?? {})).toBe("crypto.com 1 · Kalshi 1");
  });
});

describe("filterStampSections", () => {
  it("filters by focus book and canonical", () => {
    const sections = groupStampsByCanonical(
      [
        stamp({ sportsbook: "kalshi", market_type: "moneyline" }),
        stamp({ sportsbook: "crypto.com", market_type: "moneyline" }),
        stamp({ sportsbook: "kalshi", market_type: "game_total" }),
      ],
      ["moneyline", "game_total"],
    );
    const focused = filterStampSections(sections, {
      focus: { canonical: "moneyline", sportsbook: "kalshi" },
    });
    expect(focused).toHaveLength(1);
    expect(focused[0]?.canonical).toBe("moneyline");
    expect(focused[0]?.rows).toHaveLength(1);
    expect(focused[0]?.rows[0]?.sportsbook).toBe("kalshi");
  });

  it("matches a Kalshi contract side", () => {
    const sections = groupStampsByCanonical(
      [
        stamp({
          sportsbook: "kalshi",
          market_type: "moneyline",
          entity: "Kansas City Chiefs",
          side: "KC",
          contract_side: "no",
          source_id: "KXNFLGAME-26SEP27KCMIA-MIA",
        }),
        stamp({
          sportsbook: "kalshi",
          market_type: "moneyline",
          entity: "Miami Dolphins",
          side: "MIA",
          contract_side: "yes",
          source_id: "KXNFLGAME-26SEP27KCMIA-MIA",
        }),
      ],
      ["moneyline"],
    );
    const matched = filterStampSections(sections, { query: "no" });
    expect(matched[0]?.rows).toHaveLength(1);
    expect(matched[0]?.rows[0]?.entity).toBe("Kansas City Chiefs");
  });
});

describe("nextStampInspectState", () => {
  const closed = { openCanonical: null, stampBook: "", stampQuery: "" };

  it("opens with book filter from a closed row", () => {
    expect(
      nextStampInspectState(closed, { canonical: "moneyline", sportsbook: "kalshi" }),
    ).toEqual({
      openCanonical: "moneyline",
      stampBook: "kalshi",
      stampQuery: "",
    });
  });

  it("collapses when the same book×canonical link is clicked again", () => {
    expect(
      nextStampInspectState(
        { openCanonical: "moneyline", stampBook: "kalshi", stampQuery: "" },
        { canonical: "moneyline", sportsbook: "kalshi" },
      ),
    ).toEqual(closed);
  });

  it("switches book filter without collapsing", () => {
    expect(
      nextStampInspectState(
        { openCanonical: "moneyline", stampBook: "kalshi", stampQuery: "mia" },
        { canonical: "moneyline", sportsbook: "crypto.com" },
      ),
    ).toEqual({
      openCanonical: "moneyline",
      stampBook: "crypto.com",
      stampQuery: "",
    });
  });
});
