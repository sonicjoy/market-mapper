import { describe, expect, it } from "vitest";

import { matchEntityType } from "./matchEntityType";

describe("matchEntityType", () => {
  it("keeps tennis match sides on team", () => {
    expect(matchEntityType("itf_women", "tennis")).toBe("team");
    expect(matchEntityType("atp")).toBe("team");
  });

  it("uses fighter for combat sports", () => {
    expect(matchEntityType("ufc", "mma")).toBe("fighter");
    expect(matchEntityType("boxing")).toBe("fighter");
  });
});
