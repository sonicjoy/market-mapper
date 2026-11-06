/** Apply Mapper Chat ui_actions from a /chat turn. */

import { addCartItem } from "./cartStore";
import { fillMarketPrefill } from "./lib/proposedEditState";
import {
  DEFAULT_PAGE_SIZE,
  DEFAULT_RULES_KIND,
  parseKind,
  writeRulesQuery,
} from "./lib/rulesQuery";
import type { EntryLocationState } from "./types";

type CartKind = "entity_alias" | "mapping_league" | "mapping_market_rules";

type NavigateAction = { type: "navigate"; path: string };
type SwitchTabAction = { type: "switch_tab"; tab: string };
type PrefillAction = { type: "prefill_form"; tab?: string; fields?: Record<string, unknown> };
type RulesFilterAction = {
  type: "rules_filter";
  kind?: string;
  q?: string;
  league?: string[];
  sportsbook?: string[];
  canonical?: string[];
  action?: string[];
  sort?: string;
  dir?: string;
};
type CartAddAction = {
  type: "cart_add";
  items?: { kind: CartKind; label: string; payload: Record<string, unknown> }[];
};
type FocusVerifyAction = { type: "focus_verify" };

export type ChatUiAction =
  | NavigateAction
  | SwitchTabAction
  | PrefillAction
  | RulesFilterAction
  | CartAddAction
  | FocusVerifyAction;

type NavigateFn = (to: string, opts?: { state?: Record<string, unknown> }) => void;

export function applyChatUiActions(
  actions: Array<ChatUiAction | Record<string, unknown>> | undefined,
  navigate: NavigateFn,
): void {
  if (!actions?.length) return;
  let prefill: Record<string, unknown> | null = null;
  let tab: string | null = null;
  let path: string | null = null;

  // Collect before navigating: the backend emits navigate before switch_tab/prefill_form,
  // and router state has to carry the tab and fields with that single navigation.
  for (const raw of actions) {
    const action = raw as ChatUiAction;
    switch (action.type) {
      case "navigate":
        path = action.path;
        break;
      case "switch_tab":
        tab = action.tab;
        break;
      case "prefill_form":
        prefill = { ...(action.fields ?? {}) };
        tab = action.tab ?? (action.fields?.tab as string | undefined) ?? tab;
        break;
      case "rules_filter": {
        const params = writeRulesQuery(new URLSearchParams(), {
          kind: parseKind(action.kind ?? DEFAULT_RULES_KIND),
          q: action.q ?? "",
          page: 0,
          limit: DEFAULT_PAGE_SIZE,
          league: action.league ?? [],
          sportsbook: action.sportsbook ?? [],
          canonical: action.canonical ?? [],
          action: action.action ?? [],
          sort: action.sort ?? "",
          dir: action.dir === "desc" ? "desc" : "asc",
        });
        path = `/rules?${params.toString()}`;
        break;
      }
      case "cart_add":
        for (const item of action.items ?? []) {
          if (!item?.payload) continue;
          addCartItem({
            kind: item.kind,
            label: item.label || "Chat suggestion",
            payload: item.payload,
          });
        }
        break;
      case "focus_verify":
        break;
      default: {
        const _exhaustive: never = action;
        void _exhaustive;
        break;
      }
    }
  }

  if (!path && !prefill && !tab) return;
  const raw = { ...(prefill ?? {}), tab: tab ?? "alias" } as EntryLocationState;
  const state = prefill || tab ? fillMarketPrefill(raw) : undefined;
  navigate(path ?? "/entry", state ? { state } : undefined);
}
