import { describe, expect, it } from "vitest";

import { applyChatUiActions } from "./chatActions";

describe("applyChatUiActions rules_filter", () => {
  it("writes dropdowns into the Rules URL", () => {
    const seen: string[] = [];
    applyChatUiActions(
      [
        {
          type: "rules_filter",
          kind: "market_rules",
          q: "spread",
          league: ["epl"],
          sportsbook: ["kalshi"],
          action: ["ignore"],
        },
      ],
      (to) => {
        seen.push(to);
      },
    );
    expect(seen).toHaveLength(1);
    const url = new URL(seen[0], "http://console.local");
    expect(url.pathname).toBe("/rules");
    expect(url.searchParams.get("kind")).toBe("market_rules");
    expect(url.searchParams.get("q")).toBe("spread");
    expect(url.searchParams.getAll("league")).toEqual(["epl"]);
    expect(url.searchParams.getAll("sportsbook")).toEqual(["kalshi"]);
    expect(url.searchParams.getAll("action")).toEqual(["ignore"]);
  });
});

describe("applyChatUiActions market prefill", () => {
  it("selects canonical market type from alias-shaped agent fields", () => {
    const seen: Array<{ to: string; state?: Record<string, unknown> }> = [];
    applyChatUiActions(
      [
        { type: "navigate", path: "/entry" },
        { type: "switch_tab", tab: "market" },
        {
          type: "prefill_form",
          tab: "market",
          fields: {
            league: "austria_ofb_cup",
            sportsbook: "crypto.com",
            code: "To Advance",
            entity_name: "to_advance",
          },
        },
      ],
      (to, opts) => {
        seen.push({ to, state: opts?.state });
      },
    );
    expect(seen).toHaveLength(1);
    expect(seen[0].to).toBe("/entry");
    expect(seen[0].state).toMatchObject({
      tab: "market",
      source_key: "To Advance",
      action: "map",
      canonical_market_type: "to_advance",
    });
  });
});
