import { describe, expect, it } from "vitest";

import { laneKeyHint } from "./catalogLookup";

describe("laneKeyHint", () => {
  it("explains the venue key only when the lane is on", () => {
    expect(laneKeyHint("crypto.com", true)).toContain("NX.F.OPT");
    expect(laneKeyHint("Polymarket (USA)", true)).toContain("yes");
    expect(laneKeyHint("crypto.com", false)).toBeNull();
    expect(laneKeyHint("crypto.com", undefined)).toBeNull();
    expect(laneKeyHint("Kalshi", true)).toBeNull();
  });
});
