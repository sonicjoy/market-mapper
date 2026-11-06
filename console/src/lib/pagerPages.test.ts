import { describe, expect, it } from "vitest";

import { pagerPageItems } from "./pagerPages";

describe("pagerPageItems", () => {
  it("returns a single page", () => {
    expect(pagerPageItems(0, 0)).toEqual([0]);
  });

  it("returns all pages when few", () => {
    expect(pagerPageItems(2, 4)).toEqual([0, 1, 2, 3, 4]);
  });

  it("collapses the middle with ellipsis", () => {
    expect(pagerPageItems(10, 19)).toEqual([0, "ellipsis", 9, 10, 11, "ellipsis", 19]);
  });

  it("includes early pages near the start", () => {
    expect(pagerPageItems(1, 19)).toEqual([0, 1, 2, "ellipsis", 19]);
  });
});
