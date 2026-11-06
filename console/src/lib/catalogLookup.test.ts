import { describe, expect, it } from "vitest";

import {
  applyCatalogPrefill,
  buildLookupKey,
  canDeactivateCatalogOverride,
  canPublishCatalogOverride,
  catalogLookupChanged,
  catalogRowSummary,
  EMPTY_OVERRIDE_FIELDS,
  isLookupCurrent,
  lookupFailedReason,
  lookupFeedbackClass,
  lookupKeysEqual,
  outsideRankWindowWarning,
  overrideFormIssues,
  prepareCatalogLookup,
  resolvedSourceIdsFromLookup,
  submitDisabledReason,
  unreadOverrideReason,
  winnerFromLookup,
  winnerPanelClass,
  winnerPanelTitle,
  winnerPrefillKey,
} from "./catalogLookup";

const baseForm = {
  sportsbook: "Kalshi",
  sourceMarketId: "KXTEST",
  sourceSelectionId: "yes",
  gameId: "g1",
  marketId: "moneyline",
  selection: "Team A",
  selectionLine: "",
  points: 0,
  selectionPoints: 0,
  groupingKey: "default",
  mappingSource: "",
  reason: "test",
};

describe("catalogLookup", () => {
  it("buildLookupKey trims source ids", () => {
    expect(
      buildLookupKey({
        sportsbook: "Kalshi",
        sourceMarketId: " KXTEST ",
        sourceSelectionId: " yes ",
      }),
    ).toEqual({
      sportsbook: "Kalshi",
      source_market_id: "KXTEST",
      source_selection_id: "yes",
    });
  });

  it("prepareCatalogLookup never parses the ticker and catalogLookupChanged clears job", () => {
    const prepared = prepareCatalogLookup({
      ...baseForm,
      sourceMarketId: "KXITFDOUBLES-26SEP17BERSCAALICHA-BERSCA",
      sourceSelectionId: "",
    });
    expect(prepared.sourceSelectionId).toBe("");
    const key = buildLookupKey(prepared);
    expect(catalogLookupChanged(key, { ...prepared, sourceMarketId: "OTHER" })).toBe(true);
    expect(catalogLookupChanged(key, prepared)).toBe(false);
  });

  it("applyCatalogPrefill copies winner fields and resolved source ids", () => {
    const next = applyCatalogPrefill(baseForm, {
      winner: {
        game_id: "g2",
        market_id: "moneyline",
        selection: "Team B",
      },
      resolved_source_market_id: "KXTEST",
      resolved_source_selection_id: "Yes",
    });
    expect(next.gameId).toBe("g2");
    expect(next.selection).toBe("Team B");
    expect(next.sourceSelectionId).toBe("Yes");
    expect(next.reason).toBe("test");
  });

  it("applyCatalogPrefill copies mapping_source from winner", () => {
    const next = applyCatalogPrefill(baseForm, {
      winner: {
        game_id: "g2",
        market_id: "moneyline",
        selection: "Team B",
        mapping_source: "HENRY",
      },
      resolved_source_market_id: "KXTEST",
      resolved_source_selection_id: "yes",
    });
    expect(next.mappingSource).toBe("HENRY");
  });

  it("catalogRowSummary includes mapping_source when present", () => {
    const lines = catalogRowSummary({
      game_id: "g1",
      mapping_source: "HENRY",
    });
    expect(lines.some((line) => line.label === "mapping_source" && line.value === "HENRY")).toBe(
      true,
    );
  });

  it("lookupKeysEqual ignores market and selection id casing", () => {
    const key = buildLookupKey(baseForm);
    expect(
      lookupKeysEqual(key, {
        ...key,
        source_market_id: "kxtest",
        source_selection_id: "YES",
      }),
    ).toBe(true);
  });

  it("resolvedSourceIdsFromLookup prefers canonical row ids", () => {
    expect(
      resolvedSourceIdsFromLookup({
        source_market_id: "KX",
        source_selection_id: "yes",
        resolved_source_market_id: "KX",
        resolved_source_selection_id: "Yes",
      }),
    ).toEqual({
      sourceMarketId: "KX",
      sourceSelectionId: "Yes",
    });
  });

  it("lookupKeysEqual detects unchanged keys", () => {
    const key = buildLookupKey(baseForm);
    expect(lookupKeysEqual(key, key)).toBe(true);
    expect(
      lookupKeysEqual(key, {
        ...key,
        source_market_id: "OTHER",
      }),
    ).toBe(false);
  });

  it("isLookupCurrent requires matching lookup key", () => {
    const key = buildLookupKey(baseForm);
    expect(isLookupCurrent(key, baseForm)).toBe(true);
    expect(
      isLookupCurrent(key, { ...baseForm, sourceMarketId: "OTHER" }),
    ).toBe(false);
  });

  it("overrideFormIssues lists missing required fields", () => {
    expect(overrideFormIssues(baseForm)).toEqual([]);
    expect(overrideFormIssues({ ...baseForm, gameId: "", reason: "" })).toEqual([
      "game_id",
      "reason",
    ]);
  });

  it("publish and deactivate share the same submit gate", () => {
    const key = buildLookupKey(baseForm);
    const gate = { form: baseForm, lookupKey: key, lookupSuccess: true };
    expect(canPublishCatalogOverride(gate)).toBe(true);
    expect(canDeactivateCatalogOverride(gate)).toBe(true);
    expect(
      canPublishCatalogOverride({
        form: { ...baseForm, sourceMarketId: "OTHER" },
        lookupKey: key,
        lookupSuccess: true,
      }),
    ).toBe(false);
  });

  it("lookupFailedReason shows when keys match but lookup errored", () => {
    const key = buildLookupKey(baseForm);
    expect(
      lookupFailedReason({
        lookupKey: key,
        form: baseForm,
        isError: true,
        errorMessage: "HTTP 500",
      }),
    ).toBe("HTTP 500");
    expect(
      lookupFailedReason({
        lookupKey: key,
        form: { ...baseForm, sourceMarketId: "OTHER" },
        isError: true,
        errorMessage: "HTTP 500",
      }),
    ).toBeNull();
  });

  it("submitDisabledReason explains stale lookup only", () => {
    const key = buildLookupKey(baseForm);
    expect(
      submitDisabledReason({
        form: { ...baseForm, sourceMarketId: "OTHER" },
        lookupKey: key,
        lookupSuccess: true,
      }),
    ).toMatch(/Look up the current RFQ key/);
    expect(
      submitDisabledReason({
        form: baseForm,
        lookupKey: key,
        lookupSuccess: true,
      }),
    ).toBeNull();
  });

  it("outsideRankWindowWarning is advisory", () => {
    expect(
      outsideRankWindowWarning({ candidateCount: 1, inRankWindow: false }),
    ).toMatch(/opticodds_fixtures/);
    expect(
      outsideRankWindowWarning({ candidateCount: 1, inRankWindow: true }),
    ).toBeNull();
  });

  it("lookupFeedbackClass uses amber for outside-window hits", () => {
    expect(
      lookupFeedbackClass({ candidate_count: 1, in_rank_window: false }),
    ).toContain("amber");
    expect(
      lookupFeedbackClass({ candidate_count: 0, in_rank_window: null }),
    ).toContain("slate");
    expect(
      lookupFeedbackClass({ candidate_count: 1, in_rank_window: true }),
    ).toContain("emerald");
  });

  it("winnerPanelClass matches lookup tone", () => {
    expect(winnerPanelClass(false)).toContain("amber");
    expect(winnerPanelClass(true)).toContain("emerald");
  });

  it("winnerPanelTitle distinguishes stamped winners", () => {
    expect(winnerPanelTitle({ is_rfq_winner: true }, true)).toBe("Winner");
    expect(winnerPanelTitle({ is_rfq_winner: null }, false)).toBe(
      "Mapped row (outside rank window)",
    );
  });

  it("catalogRowSummary renders known fields", () => {
    const lines = catalogRowSummary({
      game_id: "g1",
      market_id: "moneyline",
      is_rfq_winner: true,
    });
    expect(lines.some((line) => line.label === "game_id" && line.value === "g1")).toBe(true);
    expect(lines.some((line) => line.label === "is_rfq_winner" && line.value === "true")).toBe(true);
  });

  it("winnerFromLookup maps lookup winner into override fields", () => {
    expect(
      winnerFromLookup({
        game_id: "g1",
        market_id: "moneyline",
        selection: "Team A",
        grouping_key: "default",
      }),
    ).toEqual({
      ...EMPTY_OVERRIDE_FIELDS,
      gameId: "g1",
      marketId: "moneyline",
      selection: "Team A",
    });
    expect(winnerFromLookup(null)).toBeNull();
  });

  it("winnerPrefillKey changes when winner payload changes", () => {
    const key = buildLookupKey(baseForm);
    const first = winnerPrefillKey(key, {
      game_id: "g1",
      market_id: "moneyline",
      selection: "Team A",
    });
    const second = winnerPrefillKey(key, {
      game_id: "g2",
      market_id: "moneyline",
      selection: "Team A",
    });
    expect(first).not.toEqual(second);
    expect(winnerPrefillKey(key, null)).toContain("empty");
  });

  it("overrideFormIssues rejects invalid numeric fields", () => {
    expect(
      overrideFormIssues({ ...baseForm, points: Number.NaN }),
    ).toContain("points");
  });
});

describe("unreadOverrideReason", () => {
  const unread = { "crypto.com": "reads market_mapping", "Polymarket (USA)": "reads market_mapping too" };

  it("matches the sportsbook case-insensitively", () => {
    expect(unreadOverrideReason(unread, "crypto.com")).toBe("reads market_mapping");
    expect(unreadOverrideReason(unread, "polymarket (usa)")).toBe("reads market_mapping too");
  });

  it("returns null for venues that read overrides or when meta is missing", () => {
    expect(unreadOverrideReason(unread, "Kalshi")).toBeNull();
    expect(unreadOverrideReason(undefined, "crypto.com")).toBeNull();
    expect(unreadOverrideReason(unread, "")).toBeNull();
  });
});
