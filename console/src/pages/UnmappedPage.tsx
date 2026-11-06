import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, Fragment } from "react";
import { Link } from "react-router-dom";

import { listUnmappedLegs, searchRules } from "../api";
import { FixturePhaseTabs } from "../components/FixturePhaseTabs";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import { RulesPager } from "../components/RulesPager";
import { SortTh } from "../components/SortTh";
import { UnmappedRowWhy } from "../components/UnmappedRowWhy";
import { publishConsoleView } from "../consoleView";
import { formatFixtureStart } from "../lib/coverageList";
import { nextSort } from "../lib/rulesQuery";
import { readUnmappedQuery, writeUnmappedQuery, type UnmappedQueryState } from "../lib/unmappedQuery";
import { usePageFilters } from "../usePageFilters";

const SPORTSBOOKS = [
  { value: "kalshi", label: "Kalshi" },
  { value: "crypto", label: "crypto.com" },
  { value: "polymarket", label: "Polymarket" },
  { value: "polymarketus", label: "Polymarket US" },
  { value: "novig", label: "Novig" },
  { value: "prophetx", label: "ProphetX" },
  { value: "underdog", label: "Underdog" },
  { value: "dkex", label: "DraftKings Exchange" },
] as const;

function sportsbookLabel(platform: string): string {
  return SPORTSBOOKS.find((row) => row.value === platform)?.label ?? platform;
}

export function UnmappedPage() {
  const [params, setParams] = usePageFilters("unmapped");
  const { platform, sport, league, q, phase, sort, dir, page, limit: pageSize } =
    readUnmappedQuery(params);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const leaguesQuery = useQuery({
    queryKey: ["tip-leagues-full"],
    queryFn: () => searchRules("", "leagues", { limit: 500 }),
  });
  const tipLeagues = leaguesQuery.data?.leagues ?? [];
  const sports = useMemo(
    () => [...new Set(tipLeagues.map((row) => row.sport).filter(Boolean))].sort(),
    [tipLeagues],
  );
  const leagueOptions = useMemo(() => {
    const rows = sport ? tipLeagues.filter((row) => row.sport === sport) : tipLeagues;
    return rows
      .map((row) => ({ value: row.league, label: row.league_label || row.league }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [sport, tipLeagues]);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["unmapped", platform, sport, league, q, phase, sort, dir, page, pageSize],
    queryFn: () =>
      listUnmappedLegs({
        platform: platform || undefined,
        sport: sport || undefined,
        league: league || undefined,
        q: q || undefined,
        phase,
        sort,
        dir,
        limit: pageSize,
        offset: page * pageSize,
      }),
  });

  useEffect(() => {
    publishConsoleView({
      path: "/unmapped",
      unmapped: { league, sport, platform, q },
    });
  }, [league, sport, platform, q]);

  function patchFilters(patch: Partial<UnmappedQueryState>, opts?: { replace?: boolean }) {
    setExpandedKey(null);
    setParams(writeUnmappedQuery(params, { page: 0, ...patch }), opts);
  }

  function onSort(column: string) {
    patchFilters(nextSort(sort, dir, column));
  }

  return (
    <div>
      <PageHeader
        title="Unmapped legs"
        description="RFQ inventory — presence does not require mapping. Live and pre tabs exclude completed fixtures; delayed counts as pre."
      >
        <RefreshButton busy={isFetching} onClick={() => void refetch()} />
      </PageHeader>
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1">
          <label className="label" htmlFor="unmapped-q">
            Search
          </label>
          <input
            id="unmapped-q"
            className="input w-full"
            placeholder="Description, fixture, or key"
            value={q}
            onChange={(e) => {
              patchFilters({ q: e.target.value }, { replace: true });
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="unmapped-sport">
            Sport
          </label>
          <select
            id="unmapped-sport"
            className="input w-44"
            value={sport}
            onChange={(e) => {
              const nextSport = e.target.value;
              const current = tipLeagues.find((row) => row.league === league);
              const leagueGone = Boolean(league && nextSport && current?.sport !== nextSport);
              patchFilters({ sport: nextSport, league: leagueGone ? "" : league });
            }}
          >
            <option value="">All</option>
            {sports.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="unmapped-league">
            League
          </label>
          <select
            id="unmapped-league"
            className="input w-56"
            value={league}
            onChange={(e) => {
              patchFilters({ league: e.target.value });
            }}
          >
            <option value="">All</option>
            {leagueOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="unmapped-book">
            Sportsbook
          </label>
          <select
            id="unmapped-book"
            className="input w-44"
            value={platform}
            onChange={(e) => {
              patchFilters({ platform: e.target.value });
            }}
          >
            <option value="">All</option>
            {SPORTSBOOKS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {data?.error ? <p className="mb-2 text-sm text-red-600">{data.error}</p> : null}
      <FixturePhaseTabs
        phase={phase}
        onChange={(nextPhase) => {
          patchFilters({ phase: nextPhase });
        }}
      />
      {isLoading ? <p className="text-sm text-slate-500">Loading…</p> : null}
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
            <tr>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2">Sport</th>
              <th className="px-3 py-2">League</th>
              <th className="px-3 py-2">Fixture</th>
              <th className="px-3 py-2">Sportsbook</th>
              <SortTh column="demand" label="Demand" sort={sort} dir={dir} onSort={onSort} />
              <SortTh column="start" label="Start" sort={sort} dir={dir} onSort={onSort} />
              <th className="px-3 py-2 w-16" />
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((row) => {
              const rowKey = `${row.platform}:${row.key}`;
              const isExpanded = expandedKey === rowKey;
              return (
                <Fragment key={rowKey}>
                  <tr className="border-b border-slate-100 dark:border-slate-800">
                    <td className="px-3 py-2 font-medium">{row.platform_leg_description || row.key}</td>
                    <td className="px-3 py-2">{row.sport || "—"}</td>
                    <td className="px-3 py-2">{row.league_label || row.league || "—"}</td>
                    <td className="px-3 py-2">{row.fixture || "—"}</td>
                    <td className="px-3 py-2">{sportsbookLabel(row.platform)}</td>
                    <td className="px-3 py-2">{row.demand}</td>
                    <td className="px-3 py-2">{formatFixtureStart(row.start_date)}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        aria-expanded={isExpanded}
                        onClick={() => setExpandedKey(isExpanded ? null : rowKey)}
                      >
                        Why
                      </button>
                      {row.platform === "kalshi" ? (
                        <Link
                          className="btn-ghost ml-1 text-xs"
                          to={`/bulk-override?event=${encodeURIComponent(row.key)}`}
                          title="Override every unmapped selection of this event in one batch"
                        >
                          Bulk override
                        </Link>
                      ) : null}
                    </td>
                  </tr>
                  {isExpanded ? (
                    <tr key={`${rowKey}:why`} className="border-b border-slate-100 dark:border-slate-800">
                      <td className="px-3 py-3" colSpan={8}>
                        <UnmappedRowWhy row={row} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <RulesPager
        count={data?.count ?? 0}
        page={page}
        pageSize={pageSize}
        onPage={(nextPage) => {
          setExpandedKey(null);
          setParams(writeUnmappedQuery(params, { page: nextPage }));
        }}
        onPageSize={(size) => {
          setExpandedKey(null);
          setParams(writeUnmappedQuery(params, { limit: size, page: 0 }));
        }}
      />
    </div>
  );
}
