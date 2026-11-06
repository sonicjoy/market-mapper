import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getUnmappedLegWhy, stageUnmappedLeg } from "../api";
import { addCartItem } from "../cartStore";
import type { MappableItem, UnmappedLegRow, UnmappedWhyReason } from "../types";

type Props = {
  row: UnmappedLegRow;
};

function badgeClass(item: MappableItem, selected: boolean): string {
  const base =
    "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors disabled:cursor-default";
  if (item.mapped) {
    return `${base} bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200`;
  }
  if (!item.fixable) {
    return `${base} bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400`;
  }
  if (selected) {
    return `${base} bg-brand-100 text-brand-900 ring-1 ring-brand-400 dark:bg-brand-950 dark:text-brand-100`;
  }
  return `${base} bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600`;
}

function kindPrefix(kind: MappableItem["kind"]): string {
  switch (kind) {
    case "league":
      return "League";
    case "market_rule":
      return "Rule";
    case "alias":
      return "Alias";
    default: {
      const _exhaustive: never = kind;
      return _exhaustive;
    }
  }
}

function Reasons({ reasons }: { reasons: UnmappedWhyReason[] }) {
  if (!reasons.length) return null;
  return (
    <ul className="space-y-1">
      {reasons.map((reason) => (
        <li
          key={reason.code}
          className={
            reason.actionable
              ? "text-xs text-slate-700 dark:text-slate-200"
              : "text-xs text-slate-500"
          }
        >
          {reason.text}
        </li>
      ))}
    </ul>
  );
}

export function UnmappedRowWhy({ row }: Props) {
  const why = useQuery({
    queryKey: [
      "unmapped",
      "why",
      row.platform,
      row.key,
      row.league,
      row.fixture,
      row.market_group,
      row.contract_type,
      row.crypto_ids?.join(","),
      row.start_date,
    ],
    queryFn: () => getUnmappedLegWhy(row),
    enabled: Boolean(row.platform && row.key),
  });
  const items = why.data?.mappable_items ?? [];
  const reasons = why.data?.reasons ?? [];
  const fixableIds = useMemo(
    () => items.filter((item) => !item.mapped && item.fixable).map((item) => item.id),
    [items],
  );
  const [selected, setSelected] = useState<Set<string>>(() => new Set(fixableIds));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const fixableKey = fixableIds.join("|");
  useEffect(() => {
    setSelected(new Set(fixableKey ? fixableKey.split("|") : []));
  }, [fixableKey]);

  if (why.isLoading) {
    return <p className="text-xs text-slate-500">Loading mapping breakdown…</p>;
  }
  if (why.isError) {
    return (
      <p className="text-xs text-red-600">
        Could not load mapping breakdown
        {why.error?.message ? `: ${why.error.message}` : "."}
      </p>
    );
  }

  function toggle(id: string, item: MappableItem) {
    if (item.mapped || !item.fixable) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onAddToCart() {
    const itemIds = [...selected];
    if (!itemIds.length) {
      setMessage("Select at least one fixable item.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const staged = await stageUnmappedLeg({
        platform: row.platform,
        key: row.key,
        item_ids: itemIds,
        platform_leg_description: row.platform_leg_description,
        league: row.league,
        fixture: row.fixture,
        sport: row.sport,
        market_group: row.market_group,
        contract_type: row.contract_type,
        crypto_ids: row.crypto_ids,
      });
      if (!staged.ok) {
        setMessage(staged.error || "Could not stage cart items.");
        return;
      }
      for (const item of staged.cart_items) {
        addCartItem({
          kind: item.kind,
          label: item.label,
          payload: item.payload,
        });
      }
      setMessage(`Added ${staged.cart_items.length} item(s).`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not add to cart.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
      <Reasons reasons={reasons} />
      {items.length ? (
        <>
          <p className="text-[10px] text-slate-500">
            Green = on tip. Click a missing alias to select it, then Add to
            cart. Disabled grey = not cart-fixable from this row.
          </p>
          <div className="flex flex-wrap gap-1">
            {items.map((item) => {
              const isSelected = selected.has(item.id);
              return (
                <button
                  key={item.id}
                  type="button"
                  className={badgeClass(item, isSelected)}
                  disabled={item.mapped || !item.fixable}
                  title={`${kindPrefix(item.kind)}: ${item.label}`}
                  onClick={() => toggle(item.id, item)}
                >
                  {item.kind === "league" ? item.label : `${kindPrefix(item.kind)}: ${item.label}`}
                </button>
              );
            })}
          </div>
        </>
      ) : null}
      {fixableIds.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={busy || selected.size === 0}
            onClick={() => void onAddToCart()}
          >
            {busy ? "Adding…" : "Add to cart"}
          </button>
          {message ? (
            <span className="text-[10px] text-slate-500">
              {message}{" "}
              {message.startsWith("Added") ? (
                <Link className="underline" to="/cart">
                  Open cart
                </Link>
              ) : null}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
