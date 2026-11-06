import { useEffect, useState } from "react";

export type CartItemKind = "entity_alias" | "mapping_league" | "mapping_market_rules";

export type CartItem = {
  id: string;
  kind: CartItemKind;
  label: string;
  payload: Record<string, unknown>;
};

const STORAGE_KEY = "mapping-console-staging-cart";

type Listener = () => void;

const listeners = new Set<Listener>();

function readStorage(): CartItem[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as CartItem[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

let items: CartItem[] = typeof sessionStorage !== "undefined" ? readStorage() : [];

function persist(next: CartItem[]) {
  items = next;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  listeners.forEach((fn) => fn());
}

function newId(): string {
  return `cart_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function getCartItems(): CartItem[] {
  return items;
}

export function cartCount(): number {
  return items.length;
}

export function addCartItem(input: Omit<CartItem, "id">): CartItem {
  const item: CartItem = { ...input, id: newId() };
  persist([...items, item]);
  return item;
}

export function removeCartItem(id: string): void {
  persist(items.filter((i) => i.id !== id));
}

export function clearCart(): void {
  persist([]);
}

export function replaceCart(next: CartItem[]): void {
  persist([...next]);
}

export function updateCartItem(id: string, patch: Partial<Omit<CartItem, "id">>): void {
  persist(items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
}

export function upsertCartItem(
  id: string | undefined,
  input: Omit<CartItem, "id">,
): CartItem {
  if (id && items.some((item) => item.id === id)) {
    const next: CartItem = { id, ...input };
    persist(items.map((item) => (item.id === id ? next : item)));
    return next;
  }
  return addCartItem(input);
}

export function subscribeCart(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useCart(): CartItem[] {
  const [cart, setCart] = useState<CartItem[]>(() => getCartItems());
  useEffect(() => subscribeCart(() => setCart(getCartItems())), []);
  return cart;
}

export function cartLeagueSlugs(): string[] {
  const slugs = new Set<string>();
  for (const item of items) {
    if (item.kind !== "mapping_league") continue;
    const league = String(item.payload.league ?? "").trim();
    if (league) slugs.add(league);
  }
  return [...slugs].sort((a, b) => a.localeCompare(b));
}

export function cartToBatchBody(cart: CartItem[]): {
  entity_aliases: Record<string, unknown>[];
  leagues: Record<string, unknown>[];
  market_rules: Record<string, unknown>[];
} {
  const entity_aliases: Record<string, unknown>[] = [];
  const leagues: Record<string, unknown>[] = [];
  const market_rules: Record<string, unknown>[] = [];
  for (const item of cart) {
    switch (item.kind) {
      case "entity_alias":
        entity_aliases.push(item.payload);
        break;
      case "mapping_league":
        leagues.push(item.payload);
        break;
      case "mapping_market_rules":
        market_rules.push(item.payload);
        break;
      default: {
        const _exhaustive: never = item.kind;
        throw new Error(`unknown cart kind: ${_exhaustive}`);
      }
    }
  }
  return { entity_aliases, leagues, market_rules };
}
