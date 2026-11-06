import { afterEach, describe, expect, it } from "vitest";

import {
  clearProposedViewState,
  hydrateProposedSearchParams,
  isProposedReturnTo,
  parseProposedViewSnapshot,
  proposedReturnPath,
  readProposedViewState,
  writeProposedViewState,
} from "./proposedViewState";

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

describe("parseProposedViewSnapshot", () => {
  it("reads a stored working view", () => {
    const snap = parseProposedViewSnapshot({
      league: "austria_ofb_cup",
      fixture: "fx1",
      kind: "market_rule",
      hideOptic: true,
      kept: ["drop:rule:1", "alias:2"],
    });
    expect(snap).toEqual({
      league: "austria_ofb_cup",
      fixture: "fx1",
      kind: "market_rule",
      hideOptic: true,
      kept: ["drop:rule:1", "alias:2"],
    });
  });

  it("defaults unknown kind and non-boolean hideOptic", () => {
    expect(parseProposedViewSnapshot({ kind: "nope", hideOptic: "yes", kept: [1] })).toEqual({
      league: "",
      fixture: "",
      kind: "all",
      hideOptic: false,
      kept: [],
    });
  });

  it("rejects junk", () => {
    expect(parseProposedViewSnapshot(null)).toBeNull();
    expect(parseProposedViewSnapshot("not-json")).toBeNull();
    expect(parseProposedViewSnapshot([])).toBeNull();
  });
});

describe("hydrateProposedSearchParams", () => {
  const saved = parseProposedViewSnapshot({
    league: "austria_ofb_cup",
    fixture: "fx1",
    kind: "alias",
    hideOptic: true,
    kept: [],
  });

  it("fills missing league, kind, and fixture from the snapshot", () => {
    const next = hydrateProposedSearchParams(new URLSearchParams(), saved);
    expect(next?.get("league")).toBe("austria_ofb_cup");
    expect(next?.get("kind")).toBe("alias");
    expect(next?.get("fixture")).toBe("fx1");
  });

  it("does not overwrite URL values already set", () => {
    const params = new URLSearchParams("league=epl&kind=alias&fixture=fx9");
    expect(hydrateProposedSearchParams(params, saved)).toBeNull();
  });

  it("skips fixture when the restored kind hides the fixture rail", () => {
    const market = parseProposedViewSnapshot({
      league: "austria_ofb_cup",
      fixture: "fx1",
      kind: "market_rule",
      hideOptic: false,
      kept: [],
    });
    const next = hydrateProposedSearchParams(new URLSearchParams(), market);
    expect(next?.get("kind")).toBe("market_rule");
    expect(next?.get("fixture")).toBeNull();
  });
});

describe("proposedReturnPath", () => {
  it("encodes the current rail and kind filter", () => {
    expect(
      proposedReturnPath("P_abc", {
        league: "austria_ofb_cup",
        fixture: "fx1",
        kind: "alias",
      }),
    ).toBe("/review/P_abc?league=austria_ofb_cup&kind=alias&fixture=fx1");
  });

  it("omits default all-kind and fixture when the rail is league-scoped", () => {
    expect(
      proposedReturnPath("P_abc", {
        league: "austria_ofb_cup",
        fixture: "fx1",
        kind: "market_rule",
      }),
    ).toBe("/review/P_abc?league=austria_ofb_cup&kind=market_rule");
  });
});

describe("isProposedReturnTo", () => {
  it("accepts a Proposed detail path with query", () => {
    expect(isProposedReturnTo("/review/P_abc?league=epl")).toBe(true);
    expect(isProposedReturnTo("/review/P_abc")).toBe(true);
  });

  it("rejects the queue and off-site paths", () => {
    expect(isProposedReturnTo("/review")).toBe(false);
    expect(isProposedReturnTo("/entry")).toBe(false);
    expect(isProposedReturnTo("https://evil.example/review/P_abc")).toBe(false);
    expect(isProposedReturnTo("/review/../entry")).toBe(false);
  });
});

describe("read/writeProposedViewState", () => {
  const previous = typeof globalThis.sessionStorage === "undefined" ? undefined : globalThis.sessionStorage;

  afterEach(() => {
    memory.clear();
    if (previous === undefined) {
      Reflect.deleteProperty(globalThis, "sessionStorage");
    } else {
      Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: previous });
    }
  });

  it("round-trips through sessionStorage when present", () => {
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: fakeStorage });
    writeProposedViewState("P_abc", {
      league: "epl",
      fixture: "",
      kind: "all",
      hideOptic: true,
      kept: ["drop:a"],
    });
    expect(readProposedViewState("P_abc")).toEqual({
      league: "epl",
      fixture: "",
      kind: "all",
      hideOptic: true,
      kept: ["drop:a"],
    });
    clearProposedViewState("P_abc");
    expect(readProposedViewState("P_abc")).toBeNull();
  });
});
