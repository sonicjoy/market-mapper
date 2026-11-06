import { describe, expect, it } from "vitest";

import { OFFICIAL_ABSENT, officialCellText, textOrDash } from "./ruleText";

const MOV_TEXT =
  "The Underlying for this Contract is the outcome and method of victory for " +
  "<competitor> in <bout> during <time period>.";

describe("officialCellText", () => {
  it("shows a real venue description when the card has one", () => {
    expect(officialCellText(MOV_TEXT)).toBe(MOV_TEXT);
  });

  it("says when the proposal card has no official text", () => {
    expect(officialCellText(null)).toBe(OFFICIAL_ABSENT);
    expect(officialCellText("  ")).toBe(OFFICIAL_ABSENT);
  });

  it("leaves the Rules table dash for a null description", () => {
    expect(textOrDash(null)).toBe("—");
  });
});
