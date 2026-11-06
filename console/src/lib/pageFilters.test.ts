import { afterEach, describe, expect, it } from "vitest";

import {
  dockPath,
  hydratePageFilters,
  pageFilterStorageKey,
  pathWithSavedFilters,
  readPageFilters,
  writePageFilters,
} from "./pageFilters";

const memory = new Map<string, string>();

const fakeStorage: Storage = {
  get length() {
    return memory.size;
  },
  clear() {
    memory.clear();
  },
  getItem(key: string) {
    return memory.get(key) ?? null;
  },
  key() {
    return null;
  },
  removeItem(key: string) {
    memory.delete(key);
  },
  setItem(key: string, value: string) {
    memory.set(key, value);
  },
};

const previous =
  typeof globalThis.sessionStorage === "undefined" ? undefined : globalThis.sessionStorage;

describe("pageFilters", () => {
  afterEach(() => {
    memory.clear();
    if (previous === undefined) {
      Reflect.deleteProperty(globalThis, "sessionStorage");
    } else {
      Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: previous });
    }
  });

  it("round-trips query strings through sessionStorage", () => {
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: fakeStorage });
    writePageFilters("coverage", new URLSearchParams("league=epl&q=arsenal"));
    expect(pageFilterStorageKey("coverage")).toBe("mapping-console-filters:coverage");
    expect(readPageFilters("coverage")?.toString()).toBe("league=epl&q=arsenal");
    writePageFilters("coverage", new URLSearchParams());
    expect(readPageFilters("coverage")).toBeNull();
  });

  it("hydrates only when the live URL has no keys", () => {
    const saved = new URLSearchParams("sport=tennis&league=atp");
    const next = hydratePageFilters(new URLSearchParams(), saved);
    expect(next?.toString()).toBe("sport=tennis&league=atp");
    expect(hydratePageFilters(new URLSearchParams("league=epl"), saved)).toBeNull();
    expect(hydratePageFilters(new URLSearchParams(), null)).toBeNull();
  });

  it("builds a dock path from saved filters, keeping the active page query", () => {
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: fakeStorage });
    writePageFilters("unmapped", new URLSearchParams("platform=kalshi&league=atp"));
    expect(pathWithSavedFilters("/unmapped")).toBe("/unmapped?platform=kalshi&league=atp");
    expect(pathWithSavedFilters("/entry")).toBe("/entry");
    expect(dockPath("/coverage", "/coverage", "?sport=soccer")).toBe("/coverage?sport=soccer");
    expect(dockPath("/unmapped", "/rules", "")).toBe("/unmapped?platform=kalshi&league=atp");
  });
});
