import { describe, expect, it } from "vitest";

import { leagueDiffSectionLabel, leagueDiffSections } from "./leagueDiff";

describe("leagueDiffSections", () => {
  it("skips empty buckets and keeps Adding before Already live", () => {
    expect(
      leagueDiffSections({
        enable: ["Polymarket prefix pol"],
        disable: [],
        change: [],
        already: ["Optic (poland_-_ekstraklasa)"],
        other: [],
      }).map((section) => section.label),
    ).toEqual(["Adding", "Already live"]);
  });

  it("returns nothing when the diff is missing", () => {
    expect(leagueDiffSections(undefined)).toEqual([]);
  });
});

describe("leagueDiffSectionLabel", () => {
  it("labels every bucket", () => {
    expect(leagueDiffSectionLabel("enable")).toBe("Adding");
    expect(leagueDiffSectionLabel("disable")).toBe("Removing");
    expect(leagueDiffSectionLabel("change")).toBe("Changing");
    expect(leagueDiffSectionLabel("already")).toBe("Already live");
    expect(leagueDiffSectionLabel("other")).toBe("Also");
  });
});
