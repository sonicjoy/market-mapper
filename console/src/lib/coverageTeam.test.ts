import { describe, expect, it } from "vitest";

import { opticDetailLine } from "./coverageTeam";

describe("opticDetailLine", () => {
  it("joins abbr and competitor id", () => {
    expect(opticDetailLine("oid-lph", "LPH")).toBe("Optic LPH · id oid-lph");
  });

  it("marks a missing Optic abbreviation", () => {
    expect(opticDetailLine("oid-xi", "")).toBe("Optic (empty abbr) · id oid-xi");
  });

  it("returns null when Optic sent neither", () => {
    expect(opticDetailLine("", "")).toBeNull();
    expect(opticDetailLine()).toBeNull();
  });
});
