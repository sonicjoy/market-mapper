import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { addCartItem } from "../cartStore";
import {
  marketRuleRowKey,
  selectionOp,
  stageSelectedMarketRules,
  stageSelectionMessage,
} from "../lib/marketRules";
import type { PageSize, SortDir } from "../lib/rulesQuery";
import type { MarketRuleRow } from "../types";
import { RuleTextCells } from "./RuleText";
import { RulesPager } from "./RulesPager";
import { SortTh } from "./SortTh";

function selectionHint(op: ReturnType<typeof selectionOp>, selectedCount: number): string {
  switch (op) {
    case "empty":
      return "Select ignored rules to enable, or mapped rules to ignore";
    case "mixed":
      return "Select only ignored or only mapped rules";
    case "enable":
      return `${selectedCount} selected (ignore → map)`;
    case "disable":
      return `${selectedCount} selected (map → ignore)`;
    default: {
      const _exhaustive: never = op;
      return _exhaustive;
    }
  }
}

function ruleDash(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  return String(value);
}

function sideSwapLabel(value: boolean | null | undefined): string {
  if (value == null) return "—";
  return value ? "yes" : "no";
}

function bulkButtonLabel(op: ReturnType<typeof selectionOp>): string {
  switch (op) {
    case "disable":
      return "Ignore selected & add to cart";
    case "enable":
      return "Enable selected & add to cart";
    case "empty":
    case "mixed":
      return "Add selected to cart";
    default: {
      const _exhaustive: never = op;
      return _exhaustive;
    }
  }
}

export function MarketRulesTable({
  rows,
  count,
  page,
  pageSize,
  sort,
  dir,
  resetKey,
  onPropose,
  onPage,
  onPageSize,
  onSort,
}: {
  rows: MarketRuleRow[];
  count: number;
  page: number;
  pageSize: number;
  sort: string;
  dir: SortDir;
  resetKey: string;
  onPropose: (row: MarketRuleRow) => void;
  onPage: (p: number) => void;
  onPageSize: (size: PageSize) => void;
  onSort: (column: string) => void;
}) {
  const [selected, setSelected] = useState<Record<string, MarketRuleRow>>({});
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setSelected({});
    setMessage(null);
  }, [resetKey]);

  const selectedRows = Object.values(selected);
  const selectedCount = selectedRows.length;
  const op = selectionOp(selectedRows);
  const canStage = op === "enable" || op === "disable";

  function toggleRow(row: MarketRuleRow, checked: boolean) {
    const key = marketRuleRowKey(row);
    setSelected((prev) => {
      if (!checked) {
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: row };
    });
  }

  function stageSelected() {
    const result = stageSelectedMarketRules(selectedRows);
    for (const item of result.cartItems) {
      addCartItem({ kind: "mapping_market_rules", label: item.label, payload: item.payload });
    }
    setMessage(stageSelectionMessage(result));
    if (result.stagedCount) setSelected({});
  }

  return (
    <div className="panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={!canStage}
          onClick={stageSelected}
        >
          {bulkButtonLabel(op)}
        </button>
        <span className="text-xs text-slate-500 dark:text-slate-400">{selectionHint(op, selectedCount)}</span>
        {selectedCount ? (
          <button type="button" className="btn-ghost text-xs" onClick={() => setSelected({})}>
            Clear selection
          </button>
        ) : null}
      </div>
      {message ? (
        <p className="border-b border-slate-100 px-3 py-2 text-sm text-brand-800 dark:border-slate-800 dark:text-brand-200">
          {message}{" "}
          <Link className="underline" to="/cart">
            Open cart
          </Link>
        </p>
      ) : null}
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            <th className="w-8 px-3 py-2" />
            <SortTh column="league" label="League" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="sportsbook" label="Sportsbook" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="source_key" label="Source key" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="action" label="Action" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="canonical" label="Canonical type" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="line_offset" label="Line offset" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="yes_side" label="Yes side" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="side_swap" label="Side swap" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="official_description" label="Official description" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="citation_url" label="Citation" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="notes" label="Notes" sort={sort} dir={dir} onSort={onSort} />
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = marketRuleRowKey(row);
            return (
              <tr key={`${key}-${i}`} className="border-t border-slate-100 dark:border-slate-800">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.sportsbook} ${row.source_key}`}
                    checked={Boolean(selected[key])}
                    onChange={(e) => toggleRow(row, e.target.checked)}
                  />
                </td>
                <td className="px-3 py-2">{row.league_label}</td>
                <td className="px-3 py-2">{row.sportsbook_label}</td>
                <td className="px-3 py-2 font-mono">{row.source_key}</td>
                <td className="px-3 py-2">{row.action}</td>
                <td className="px-3 py-2 font-mono">{row.canonical_market_type ?? "-"}</td>
                <td className="px-3 py-2 font-mono">{row.offset_text ?? ruleDash(row.line_offset)}</td>
                <td className="px-3 py-2 font-mono">{row.yes_side_text ?? ruleDash(row.yes_side)}</td>
                <td className="px-3 py-2">{row.side_swap_text ?? sideSwapLabel(row.side_swap)}</td>
                <RuleTextCells
                  official={row.official_description}
                  citation={row.citation_url}
                  notes={row.notes}
                />
                <td className="px-3 py-2 text-right">
                  <button type="button" className="btn-ghost text-xs" onClick={() => onPropose(row)}>
                    Propose change
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {count === 0 && <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">No matches.</p>}
      <RulesPager count={count} page={page} pageSize={pageSize} onPage={onPage} onPageSize={onPageSize} />
    </div>
  );
}
