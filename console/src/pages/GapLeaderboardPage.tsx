import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { GapLeaderboardTable } from "../components/GapLeaderboardTable";
import { MultiSelect } from "../components/MultiSelect";
import { CacheNote } from "../components/CacheNote";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import { publishConsoleView } from "../consoleView";
import { listGapLeaderboard, type GapPlatform } from "../gapLeaderboardApi";
import {
  GAP_SORTS,
  GAP_WINDOWS,
  readGapLeaderboardQuery,
  writeGapLeaderboardQuery,
  type GapLeaderboardQueryState,
  type GapSort,
} from "../lib/gapLeaderboardQuery";
import { platformNodeId, searchPlatforms } from "../lib/gapLeaderboardTree";
import { usePageFilters } from "../usePageFilters";

function PlatformTile({ p, active, onClick }: { p: GapPlatform; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`card px-3 py-2 text-left ${active ? "ring-2 ring-brand-600" : "hover:bg-slate-50 dark:hover:bg-slate-800/40"}`}
    >
      <p className="text-xs text-slate-600 dark:text-slate-300">{p.label}</p>
      <p className="text-lg font-semibold tabular-nums">
        {p.demand.toLocaleString()}
        {p.demand_is_sum ? <span className="text-slate-400">*</span> : null}
        <span className="ml-1 text-xs font-normal text-slate-500">failed RFQs</span>
      </p>
      <p className="text-xs tabular-nums text-slate-500">
        {p.unmapped.toLocaleString()} unmapped
        {p.leagues_not_in_tip ? ` · ${p.leagues_not_in_tip} leagues not in tip` : ""}
      </p>
    </button>
  );
}

export function GapLeaderboardPage() {
  const [params, setParams] = usePageFilters("gap-leaderboard");
  const query = readGapLeaderboardQuery(params);
  const { hours, platforms, markets, kickoffFrom, kickoffTo, sort, q } = query;
  const [open, setOpen] = useState<Set<string>>(new Set());
  const forceRefresh = useRef(false);

  const board = useQuery({
    queryKey: ["gap-leaderboard", hours, markets, kickoffFrom, kickoffTo, sort],
    queryFn: () => {
      const refresh = forceRefresh.current;
      forceRefresh.current = false;
      return listGapLeaderboard({ hours, markets, kickoffFrom, kickoffTo, sort, refresh });
    },
    placeholderData: keepPreviousData,
    // One uncached load bills ~150 GB of BigQuery; the server memoises for 1h (CacheNote says so).
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    publishConsoleView({ path: "/gap-leaderboard" });
  }, []);

  function patch(next: Partial<GapLeaderboardQueryState>, opts?: { replace?: boolean }) {
    setParams(writeGapLeaderboardQuery(params, next), opts);
  }

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function togglePlatform(id: string) {
    patch({ platforms: platforms.includes(id) ? platforms.filter((p) => p !== id) : [...platforms, id] });
  }

  const all = board.data?.platforms ?? [];
  const shown = useMemo(() => {
    const picked = platforms.length ? all.filter((p) => platforms.includes(p.id)) : all;
    return searchPlatforms(picked, q);
  }, [all, platforms, q]);

  const marketOptions = useMemo(() => {
    const offered = board.data?.market_options ?? [];
    const seen = new Set(offered.map((o) => o.name.toLowerCase()));
    // A picked name the other filters now exclude stays listed so it can be unticked.
    const stranded = markets
      .filter((name) => !seen.has(name.toLowerCase()))
      .map((name) => ({ value: name, label: `${name} (0)` }));
    return [
      ...offered.map((o) => ({
        value: o.name,
        label: `${o.name} (${o.demand.toLocaleString()} RFQs / ${o.unmapped.toLocaleString()} unmapped)`,
      })),
      ...stranded,
    ];
  }, [board.data?.market_options, markets]);

  return (
    <div>
      <PageHeader
        title="Gap leaderboard"
        description="The biggest mapping gaps on every venue: failed RFQs in the window, plus unmapped catalogue selections where a venue catalogue is wired (crypto.com). Click a platform to filter, expand to drill down, Fix opens the page that closes the gap."
      >
        <RefreshButton
          busy={board.isFetching}
          onClick={() => {
            forceRefresh.current = true;
            return board.refetch();
          }}
        />
      </PageHeader>
      <CacheNote cachedAt={board.data?.cached_at} scanCost="about 150 GB of BigQuery" />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="gap-window">
            Failed RFQs in last
          </label>
          <select
            id="gap-window"
            className="input w-28"
            value={hours}
            onChange={(e) => patch({ hours: Number(e.target.value) })}
          >
            {GAP_WINDOWS.map((h) => (
              <option key={h} value={h}>
                {h}h
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="gap-sort">
            Rank by
          </label>
          <select
            id="gap-sort"
            className="input w-48"
            value={sort}
            onChange={(e) => patch({ sort: e.target.value as GapSort })}
          >
            {GAP_SORTS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[12rem] flex-1">
          <label className="label" htmlFor="gap-q">
            Search
          </label>
          <input
            id="gap-q"
            className="input w-full"
            placeholder="League, fixture or market"
            value={q}
            onChange={(e) => patch({ q: e.target.value }, { replace: true })}
          />
        </div>
      </div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <MultiSelect
          id="gap-markets"
          label="Markets"
          options={marketOptions}
          values={markets}
          onChange={(next) => patch({ markets: next })}
          searchable
        />
        <div>
          <label className="label" htmlFor="gap-from">
            Kickoff from (UTC)
          </label>
          <input
            id="gap-from"
            type="datetime-local"
            className="input w-52"
            value={kickoffFrom}
            max={kickoffTo || undefined}
            onChange={(e) => patch({ kickoffFrom: e.target.value }, { replace: true })}
          />
        </div>
        <div>
          <label className="label" htmlFor="gap-to">
            Kickoff to (UTC)
          </label>
          <input
            id="gap-to"
            type="datetime-local"
            className="input w-52"
            value={kickoffTo}
            min={kickoffFrom || undefined}
            onChange={(e) => patch({ kickoffTo: e.target.value }, { replace: true })}
          />
        </div>
        {kickoffFrom || kickoffTo ? (
          <button type="button" className="btn-ghost text-xs" onClick={() => patch({ kickoffFrom: "", kickoffTo: "" })}>
            Clear window
          </button>
        ) : null}
      </div>
      {board.data?.error ? <p className="notice-red mb-2 text-sm">{board.data.error}</p> : null}
      {board.isError ? <p className="notice-red mb-2 text-sm">{board.error.message}</p> : null}
      {board.isLoading ? <p className="text-sm text-slate-500">Ranking every venue's gaps…</p> : null}
      {all.length ? (
        <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-5">
          {all.map((p) => (
            <PlatformTile key={p.id} p={p} active={platforms.includes(p.id)} onClick={() => togglePlatform(p.id)} />
          ))}
        </div>
      ) : null}
      {board.data && !shown.some((p) => p.leagues.length) ? (
        <p className="text-sm text-slate-500">Nothing to show for these filters.</p>
      ) : (
        <GapLeaderboardTable
          platforms={shown}
          open={q ? new Set([...open, ...shown.map((p) => platformNodeId(p.id))]) : open}
          onToggle={toggle}
        />
      )}
      <p className="mt-2 text-[11px] text-slate-500">
        * a sum of its children, so an RFQ with legs in two of them counts twice. Kalshi 15-minute crypto and commodity
        series are excluded (no Optic book prices them). Novig, ProphetX and SX Bet legs carry only venue ids, so they
        have no league or kickoff yet; DraftKings has no kickoff.
      </p>
    </div>
  );
}
