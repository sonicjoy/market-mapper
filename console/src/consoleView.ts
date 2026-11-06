/** Structured console snapshot for Mapper Chat page_context. */

import type { CartItem } from "./cartStore";
import type { EntryLocationState } from "./types";

export type ConsoleRulesView = {
  kind?: string;
  q?: string;
  league?: string[];
  sportsbook?: string[];
  canonical?: string[];
  action?: string[];
  sort?: string;
  dir?: string;
  page?: number;
  limit?: number;
};

export type ConsoleExploreView = {
  league?: string;
  sport?: string;
  fixture?: string;
  platform?: string;
  q?: string;
};

export type ConsoleViewSnapshot = {
  path: string;
  tab?: string;
  entry: EntryLocationState;
  rules: ConsoleRulesView;
  coverage: ConsoleExploreView;
  unmapped: ConsoleExploreView;
  cart: Array<{ id: string; kind: string; label: string }>;
  review_ref?: string;
};

let snapshot: ConsoleViewSnapshot = {
  path: typeof window !== "undefined" ? window.location.pathname : "",
  entry: {},
  rules: {},
  coverage: {},
  unmapped: {},
  cart: [],
};

export function publishConsoleView(patch: Partial<ConsoleViewSnapshot>): void {
  snapshot = {
    ...snapshot,
    ...patch,
    entry: patch.entry ? { ...snapshot.entry, ...patch.entry } : snapshot.entry,
    rules: patch.rules ? { ...snapshot.rules, ...patch.rules } : snapshot.rules,
    coverage: patch.coverage ? { ...snapshot.coverage, ...patch.coverage } : snapshot.coverage,
    unmapped: patch.unmapped ? { ...snapshot.unmapped, ...patch.unmapped } : snapshot.unmapped,
    cart: patch.cart ?? snapshot.cart,
  };
}

export function publishEntryFields(fields: EntryLocationState, tab?: string): void {
  publishConsoleView({
    path: "/entry",
    tab,
    entry: { ...fields, tab: tab as EntryLocationState["tab"] },
  });
}

export function publishRulesView(rules: ConsoleRulesView): void {
  snapshot = { ...snapshot, path: "/rules", rules: { ...rules } };
}

export function publishReviewView(path: string, review_ref = ""): void {
  snapshot = { ...snapshot, path, review_ref };
}

export function publishCartItems(items: CartItem[]): void {
  publishConsoleView({
    cart: items.map((c) => ({ id: c.id, kind: c.kind, label: c.label })),
  });
}

export function getConsoleSnapshot(): ConsoleViewSnapshot {
  return {
    ...snapshot,
    path: typeof window !== "undefined" ? window.location.pathname : snapshot.path,
    entry: { ...snapshot.entry },
    rules: { ...snapshot.rules },
    coverage: { ...snapshot.coverage },
    unmapped: { ...snapshot.unmapped },
    cart: [...snapshot.cart],
  };
}
