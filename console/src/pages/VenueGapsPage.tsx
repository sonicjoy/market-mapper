import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { FixturePhaseTabs } from "../components/FixturePhaseTabs";
import { MultiSelect } from "../components/MultiSelect";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import { VenueGapsFixPanel } from "../components/VenueGapsFixPanel";
import { VenueGapsTable } from "../components/VenueGapsTable";
import { publishConsoleView } from "../consoleView";
import { arrangeLeagues, mappedPct, nodeId, type VenueGapNode } from "../lib/venueGapsTree";
import {
  VENUE_GAP_PLATFORMS,
  VENUE_GAP_SORTS,
  readVenueGapsQuery,
  writeVenueGapsQuery,
  type VenueGapSort,
  type VenueGapsQueryState,
} from "../lib/venueGapsQuery";
import { usePageFilters } from "../usePageFilters";
import {
  listVenueGaps,
  type VenueGapLeague,
  type VenueGapMarketOption,
  type VenueGapTotals,
} from "../venueGapsApi";

const TOP_MARKET_CHIPS = 8;

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="card px-3 py-2">
      <p className="text-xs text-slate-600 dark:text-slate-300">{label}</p>
      <p className="text-lg font-semibold tabular-nums">
        {value}
        {detail ? <span className="ml-1 text-xs font-normal text-slate-500">{detail}</span> : null}
      </p>
    </div>
  );
}

function Totals({ totals }: { totals: VenueGapTotals }) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
      <Stat label="Selections listed" value={totals.selections.toLocaleString()} />
      <Stat
        label="Mapped"
        value={`${mappedPct({ total: totals.selections, mapped: totals.mapped })}%`}
        detail={`${totals.mapped.toLocaleString()} rows`}
      />
      <Stat label="Leagues not in tip" value={String(totals.leagues_not_in_tip)} detail={`of ${totals.leagues}`} />
      <Stat
        label="Fixtures with nothing mapped"
        value={String(totals.fixtures_unmapped)}
        detail={`of ${totals.fixtures}`}
      />
    </div>
  );
}

/** The biggest unmapped markets as one-click filters; the ranking comes from the server. */
function MarketGapChips({
  options,
  picked,
  onToggle,
}: {
  options: VenueGapMarketOption[];
  picked: string[];
  onToggle: (name: string) => void;
}) {
  const top = options.filter((o) => o.unmapped > 0).slice(0, TOP_MARKET_CHIPS);
  if (!top.length) return null;
  const on = new Set(picked.map((name) => name.toLowerCase()));
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-slate-500">Biggest market gaps:</span>
      {top.map((o) => {
        const active = on.has(o.name.toLowerCase());
        return (
          <button
            key={o.name}
            type="button"
            aria-pressed={active}
            title={`${o.unmapped.toLocaleString()} unmapped of ${o.total.toLocaleString()} across ${o.fixtures} fixture(s)`}
            className={`rounded-full border px-2 py-0.5 ${
              active
                ? "border-brand-600 bg-brand-600 text-white"
                : "border-slate-300 text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
            }`}
            onClick={() => onToggle(o.name)}
          >
            {o.name} <span className="tabular-nums opacity-75">{o.unmapped.toLocaleString()}</span>
          </button>
        );
      })}
    </div>
  );
}

export function VenueGapsPage() {
  const [params, setParams] = usePageFilters("venue-gaps");
  const query = readVenueGapsQuery(params);
  const { platform, phase, q, unmappedOnly, sort, markets, kickoffFrom, kickoffTo } = query;
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<VenueGapNode | null>(null);
  const forceRefresh = useRef(false);

  const gaps = useQuery({
    queryKey: ["venue-gaps", platform, phase, markets, kickoffFrom, kickoffTo],
    queryFn: () => {
      const refresh = forceRefresh.current;
      forceRefresh.current = false;
      return listVenueGaps({ platform, phase, markets, kickoffFrom, kickoffTo, refresh });
    },
    placeholderData: keepPreviousData,
    staleTime: 60 * 1000,
  });

  useEffect(() => {
    publishConsoleView({ path: "/venue-gaps" });
  }, []);

  const leagues = useMemo(
    () => arrangeLeagues(gaps.data?.leagues ?? [], { sort, unmappedOnly, q }),
    [gaps.data, sort, unmappedOnly, q],
  );
  const selectedLeague = selected
    ? (gaps.data?.leagues.find((league: VenueGapLeague) => league.meta_league === selected.meta) ?? null)
    : null;

  function patch(next: Partial<VenueGapsQueryState>, opts?: { replace?: boolean }) {
    setParams(writeVenueGapsQuery(params, next), opts);
  }

  const marketOptions = useMemo(() => {
    const offered = gaps.data?.market_options ?? [];
    const seen = new Set(offered.map((o) => o.name.toLowerCase()));
    // A picked name the other filters now exclude stays listed so it can be unticked.
    const stranded = markets
      .filter((name) => !seen.has(name.toLowerCase()))
      .map((name) => ({ value: name, label: `${name} (0 unmapped)` }));
    return [
      ...offered.map((o) => ({
        value: o.name,
        label: `${o.name} (${o.unmapped.toLocaleString()} unmapped / ${o.fixtures} fx)`,
      })),
      ...stranded,
    ];
  }, [gaps.data?.market_options, markets]);

  function toggleMarket(name: string) {
    const lower = name.toLowerCase();
    const has = markets.some((m) => m.toLowerCase() === lower);
    patch({ markets: has ? markets.filter((m) => m.toLowerCase() !== lower) : [...markets, name] });
  }

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <PageHeader
        title="Venue gaps"
        description="Everything the venue lists that has not finished, against published market_mapping. Pick a node to draft the rules it is missing and stage them in the Cart."
      >
        <RefreshButton
          busy={gaps.isFetching}
          onClick={() => {
            forceRefresh.current = true;
            return gaps.refetch();
          }}
        />
      </PageHeader>
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="venue-gaps-platform">
            Platform
          </label>
          <select
            id="venue-gaps-platform"
            className="input w-40"
            value={platform}
            onChange={(e) => patch({ platform: e.target.value })}
          >
            {VENUE_GAP_PLATFORMS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[12rem] flex-1">
          <label className="label" htmlFor="venue-gaps-q">
            Search
          </label>
          <input
            id="venue-gaps-q"
            className="input w-full"
            placeholder="League, fixture, or symbol prefix"
            value={q}
            onChange={(e) => patch({ q: e.target.value }, { replace: true })}
          />
        </div>
        <div>
          <label className="label" htmlFor="venue-gaps-sort">
            Sort
          </label>
          <select
            id="venue-gaps-sort"
            className="input w-44"
            value={sort}
            onChange={(e) => patch({ sort: e.target.value as VenueGapSort })}
          >
            {VENUE_GAP_SORTS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 pb-1.5 text-sm text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            className="h-4 w-4 accent-brand-600"
            checked={unmappedOnly}
            onChange={(e) => patch({ unmappedOnly: e.target.checked })}
          />
          Unmapped only
        </label>
      </div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <MultiSelect
          id="venue-gaps-markets"
          label="Markets"
          options={marketOptions}
          values={markets}
          onChange={(next) => patch({ markets: next })}
          searchable
        />
        <div>
          <label className="label" htmlFor="venue-gaps-from">
            Kickoff from (UTC)
          </label>
          <input
            id="venue-gaps-from"
            type="datetime-local"
            className="input w-52"
            value={kickoffFrom}
            max={kickoffTo || undefined}
            onChange={(e) => patch({ kickoffFrom: e.target.value }, { replace: true })}
          />
        </div>
        <div>
          <label className="label" htmlFor="venue-gaps-to">
            Kickoff to (UTC)
          </label>
          <input
            id="venue-gaps-to"
            type="datetime-local"
            className="input w-52"
            value={kickoffTo}
            min={kickoffFrom || undefined}
            onChange={(e) => patch({ kickoffTo: e.target.value }, { replace: true })}
          />
        </div>
        {kickoffFrom || kickoffTo ? (
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={() => patch({ kickoffFrom: "", kickoffTo: "" })}
          >
            Clear window
          </button>
        ) : null}
      </div>
      <MarketGapChips options={gaps.data?.market_options ?? []} picked={markets} onToggle={toggleMarket} />
      <FixturePhaseTabs phase={phase} onChange={(next) => patch({ phase: next })} />
      {gaps.data?.error ? <p className="notice-red mb-2 text-sm">{gaps.data.error}</p> : null}
      {gaps.isError ? <p className="notice-red mb-2 text-sm">{gaps.error.message}</p> : null}
      {gaps.data ? <Totals totals={gaps.data.totals} /> : null}
      {gaps.isLoading ? <p className="text-sm text-slate-500">Loading the venue catalogue…</p> : null}
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
          {gaps.data && !leagues.length ? (
            <p className="text-sm text-slate-500">Nothing to show for these filters.</p>
          ) : (
            <VenueGapsTable
              platform={platform}
              leagues={leagues}
              unmappedOnly={unmappedOnly}
              markets={markets}
              selectedId={selected ? nodeId(selected) : null}
              open={open}
              onSelect={setSelected}
              onToggle={toggle}
            />
          )}
        </div>
        <div className="w-full shrink-0 xl:sticky xl:top-4 xl:w-96">
          <VenueGapsFixPanel platform={platform} node={selected} league={selectedLeague} markets={markets} />
        </div>
      </div>
    </div>
  );
}
