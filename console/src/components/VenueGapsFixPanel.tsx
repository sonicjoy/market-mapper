import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { addCartItem } from "../cartStore";
import { nodeId, sampleRows, type VenueGapNode } from "../lib/venueGapsTree";
import type { EntryLocationState, UnmappedWhyReason } from "../types";
import {
  FIXTURE_STALE_MS,
  fixtureQueryKey,
  getVenueGapFixture,
  getVenueGapWhy,
  stageVenueGap,
  type VenueGapFixtureDetail,
  type VenueGapLeague,
  type VenueGapLegRow,
  type VenueGapStageResult,
  type VenueGapWhyItem,
} from "../venueGapsApi";

type Props = {
  platform: string;
  node: VenueGapNode | null;
  league: VenueGapLeague | null;
  /** Picked market names: a fixture node drafts rules for these markets only. */
  markets?: string[];
};

const KIND_LABEL: Record<VenueGapWhyItem["kind"], string> = {
  league: "League",
  alias: "Alias",
  market_rule: "Market rule",
};

function PanelShell({ title, eyebrow, children }: { title: string; eyebrow: string; children: ReactNode }) {
  return (
    <aside className="card space-y-3" aria-label="Rules for the selected node">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{eyebrow}</p>
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
      </div>
      {children}
    </aside>
  );
}

function LeagueFix({ league }: { league: VenueGapLeague }) {
  const navigate = useNavigate();
  const { tip } = league;
  if (tip.status === "in_tip") {
    return (
      <p className="text-xs text-slate-600 dark:text-slate-300">
        On the tip as <span className="font-mono">{tip.league}</span>. Pick a fixture, market or selection to
        draft the rules it is missing.
      </p>
    );
  }
  const text =
    tip.status === "disabled"
      ? `${tip.league} pins crypto.com league ${league.meta_league} but the league or its crypto.com exchange is off.`
      : tip.fix?.action === "amend"
        ? `${tip.league} is on the tip without a crypto.com pin for ${league.meta_league}.`
        : `No tip league pins crypto.com league ${league.meta_league}. Onboard it: pick the slug, sport and Optic league.`;
  return (
    <div className="space-y-2">
      <p className="notice-amber text-xs">{text}</p>
      {tip.fix ? (
        <button
          type="button"
          className="btn-primary text-xs"
          onClick={() => navigate("/entry", { state: tip.fix?.entry_state })}
        >
          {tip.fix.action === "amend" ? `Open ${tip.league} with crypto.com pinned` : "Open league form (prefilled)"}
        </button>
      ) : (
        <p className="text-xs text-slate-500">crypto.com sends these without a league; nothing to pin.</p>
      )}
      <p className="text-[11px] text-slate-500">
        The Editor runs the league dry-run (Optic league id, parser profile) before it goes to the Cart.
      </p>
    </div>
  );
}

function ItemLabel({ item }: { item: VenueGapWhyItem }) {
  return (
    <>
      <span className="mr-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {KIND_LABEL[item.kind]}
      </span>
      <span className="font-mono text-slate-900 dark:text-slate-100">{item.label}</span>
    </>
  );
}

function DraftableItem(props: { item: VenueGapWhyItem; checked: boolean; onToggle: () => void }) {
  const id = `vg-item-${props.item.id}`;
  return (
    <li className="flex items-start gap-2 rounded-md border border-slate-200 p-2 dark:border-slate-700">
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4 accent-brand-600"
        checked={props.checked}
        onChange={props.onToggle}
      />
      <label htmlFor={id} className="min-w-0 flex-1 text-xs">
        <ItemLabel item={props.item} />
      </label>
    </li>
  );
}

function SettledItems({ title, items }: { title: string; items: VenueGapWhyItem[] }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1 text-[11px] font-medium text-slate-500">
        {title} ({items.length})
      </p>
      <ul className="space-y-0.5 text-xs">
        {items.map((item) => (
          <li key={item.id}>
            <ItemLabel item={item} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function StageOutcome({ result }: { result: VenueGapStageResult }) {
  const navigate = useNavigate();
  return (
    <div className="space-y-2 text-xs">
      {result.cart_items.length ? (
        <p className="notice-brand">
          Added {result.cart_items.length} rule(s) to the cart.{" "}
          <Link className="font-medium underline" to="/cart">
            Open cart
          </Link>
        </p>
      ) : null}
      {result.needs_editor.map((entry) => (
        <div key={entry.label} className="notice-amber flex items-center justify-between gap-2">
          <span>
            <span className="font-mono">{entry.label}</span>: no tip entity matched. Pick it in the Editor.
          </span>
          <button
            type="button"
            className="btn-ghost shrink-0 text-xs"
            onClick={() => navigate("/entry", { state: entry.entry_state as EntryLocationState })}
          >
            Open in Editor
          </button>
        </div>
      ))}
    </div>
  );
}

function NodeFix({ platform, node, rows }: { platform: string; node: VenueGapNode; rows: VenueGapLegRow[] }) {
  const why = useQuery({
    queryKey: ["venue-gaps", "why", platform, nodeId(node), rows.map((r) => r.key).join("|")],
    queryFn: () => getVenueGapWhy(platform, rows),
    enabled: rows.length > 0,
    staleTime: FIXTURE_STALE_MS,
  });
  const items = why.data?.mappable_items ?? [];
  const draftable = useMemo(
    () => items.filter((i: VenueGapWhyItem) => i.fixable && !i.mapped).map((i: VenueGapWhyItem) => i.id),
    [items],
  );
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<VenueGapStageResult | null>(null);
  const draftKey = draftable.join("|");
  useEffect(() => {
    setPicked(new Set(draftKey ? draftKey.split("|") : []));
    setResult(null);
    setError("");
  }, [draftKey]);

  if (!rows.length) {
    return <p className="text-xs text-slate-600 dark:text-slate-300">Every selection here is mapped.</p>;
  }
  if (why.isLoading) {
    return <p className="text-xs text-slate-500">Drafting rules from {rows.length} selection(s)…</p>;
  }
  if (why.isError) {
    return <p className="notice-red text-xs">Could not draft rules: {why.error.message}</p>;
  }

  async function onStage() {
    setBusy(true);
    setError("");
    try {
      const out = await stageVenueGap(platform, rows, [...picked]);
      if (!out.ok) {
        setError(out.error || "Could not draft cart items.");
        return;
      }
      for (const item of out.cart_items) addCartItem(item);
      setResult(out);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stage rules.");
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-1">
        {(why.data?.reasons ?? []).map((reason: UnmappedWhyReason) => (
          <li key={reason.code} className="text-xs text-slate-700 dark:text-slate-200">
            {reason.text}
          </li>
        ))}
      </ul>
      {draftable.length ? (
        <ul className="space-y-1.5">
          {items
            .filter((item: VenueGapWhyItem) => item.fixable && !item.mapped)
            .map((item: VenueGapWhyItem) => (
              <DraftableItem
                key={item.id}
                item={item}
                checked={picked.has(item.id)}
                onToggle={() => toggle(item.id)}
              />
            ))}
        </ul>
      ) : null}
      <SettledItems title="Already on tip" items={items.filter((item: VenueGapWhyItem) => item.mapped)} />
      <SettledItems
        title="Not draftable"
        items={items.filter((item: VenueGapWhyItem) => !item.mapped && !item.fixable)}
      />
      {draftable.length ? (
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={busy || picked.size === 0}
          onClick={() => void onStage()}
        >
          {busy ? "Staging…" : `Stage ${picked.size} rule(s) in Cart`}
        </button>
      ) : null}
      {error ? <p className="notice-red text-xs">{error}</p> : null}
      {result ? <StageOutcome result={result} /> : null}
      <p className="text-[11px] text-slate-500">
        Drafted from {why.data?.sampled ?? rows.length} unmapped selection(s). Market rules apply league-wide, so one
        rule can map this market in every fixture. Counts refresh after the next mapper run.
      </p>
    </div>
  );
}

export function VenueGapsFixPanel({ platform, node, league, markets = [] }: Props) {
  const fixtureKey = node && node.kind !== "league" ? node.fixtureKey : "";
  const detail = useQuery({
    queryKey: fixtureQueryKey(platform, fixtureKey),
    queryFn: () => getVenueGapFixture(platform, fixtureKey),
    enabled: Boolean(fixtureKey),
    staleTime: FIXTURE_STALE_MS,
  });
  if (!node || !league) {
    return (
      <PanelShell eyebrow="Rules" title="Nothing selected">
        <p className="text-xs text-slate-600 dark:text-slate-300">
          Click a league, fixture, market or selection to see which rules would map it.
        </p>
      </PanelShell>
    );
  }
  const title = node.kind === "league" ? (league.tip.league_label ?? league.meta_league) : titleFor(node, detail.data);
  if (node.kind === "league" || league.tip.status !== "in_tip") {
    return (
      <PanelShell eyebrow={node.kind === "league" ? "League" : `${node.kind} · league not on tip`} title={title}>
        <LeagueFix league={league} />
      </PanelShell>
    );
  }
  return (
    <PanelShell eyebrow={node.kind} title={title}>
      {detail.isLoading ? <p className="text-xs text-slate-500">Loading fixture…</p> : null}
      {detail.isError || detail.data?.error ? (
        <p className="notice-red text-xs">
          Could not load fixture: {detail.data?.error ?? detail.error?.message ?? "unknown error"}
        </p>
      ) : null}
      {detail.data && !detail.data.error ? <NodeFix key={nodeId(node)} platform={platform} node={node} rows={sampleRows(node, detail.data, markets)} /> : null}
    </PanelShell>
  );
}

function titleFor(node: Exclude<VenueGapNode, { kind: "league" }>, detail?: VenueGapFixtureDetail): string {
  if (!detail) return node.fixtureKey;
  if (node.kind === "fixture") return detail.name ?? node.fixtureKey;
  const market = detail.markets.find((m) => m.market_id === node.marketId);
  if (node.kind === "market") return market?.label ?? node.marketId;
  return market?.selections.find((s) => s.key === node.key)?.outcome ?? node.key;
}
