import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useState } from "react";

import { listMissingSymbols, searchRules } from "../api";
import { MultiSelect } from "../components/MultiSelect";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import { RulesPager } from "../components/RulesPager";
import { TableFetchOverlay } from "../components/TableFetchOverlay";
import { SortTh } from "../components/SortTh";
import { UnmappedRowWhy } from "../components/UnmappedRowWhy";
import { publishConsoleView } from "../consoleView";
import { formatFixtureStart } from "../lib/coverageList";
import {
  platformLabel,
  platformsForMissing,
  useExplorePlatforms,
} from "../lib/explorePlatforms";
import {
  missingScopeLabel,
  readMissingQuery,
  writeMissingQuery,
  type MissingQueryState,
} from "../lib/missingQuery";
import { missingRowToUnmapped } from "../lib/missingUnmappedRow";
import { nextSort } from "../lib/rulesQuery";
import { usePageFilters } from "../usePageFilters";

const SCOPES = [
  { value: "all", label: "All symbols" },
  { value: "untouched", label: "Fixture" },
  { value: "extra", label: "Market" },
] as const;

export function MissingPage() {
  const explorePlatforms = useExplorePlatforms();
  const platformOptions = platformsForMissing(explorePlatforms);
  const [params, setParams] = usePageFilters("missing");
  const {
    platform,
    sport,
    league,
    scope,
    marketGroup,
    contractTypes,
    kickoffFrom,
    kickoffTo,
    q,
    sort,
    dir,
    page,
    limit: pageSize,
  } = readMissingQuery(params);
  const [refresh, setRefresh] = useState(false);
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
    queryKey: [
      "missing",
      platform,
      sport,
      league,
      scope,
      marketGroup,
      contractTypes,
      kickoffFrom,
      kickoffTo,
      q,
      sort,
      dir,
      page,
      pageSize,
      refresh,
    ],
    queryFn: () =>
      listMissingSymbols({
        platform: platform || undefined,
        sport: sport || undefined,
        league: league || undefined,
        scope,
        market_group: marketGroup || undefined,
        contract_type: contractTypes,
        kickoff_from: kickoffFrom || undefined,
        kickoff_to: kickoffTo || undefined,
        q: q || undefined,
        sort,
        dir,
        limit: pageSize,
        offset: page * pageSize,
        refresh,
      }),
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    if (!isFetching && refresh) {
      setRefresh(false);
    }
  }, [isFetching, refresh]);

  useEffect(() => {
    publishConsoleView({
      path: "/missing",
      unmapped: { league, sport, platform, q },
    });
  }, [league, sport, platform, q]);

  function patchFilters(patch: Partial<MissingQueryState>, opts?: { replace?: boolean }) {
    setParams(writeMissingQuery(params, { page: 0, ...patch }), opts);
  }

  function onSort(column: string) {
    patchFilters(nextSort(sort, dir, column));
  }

  const cacheNote =
    data?.cache_age_sec != null
      ? `Catalogue cache ${Math.round(data.cache_age_sec)}s old — Refresh re-queries BigQuery.`
      : null;
  const showNxColumn = platform === "crypto";
  const marketOptions = useMemo(() => {
    const offered = data?.market_options ?? [];
    const seen = new Set(offered.map((o) => o.name.toLowerCase()));
    // A selected name the other filters now exclude stays visible so it can be unticked.
    const stranded = contractTypes
      .filter((name) => !seen.has(name.toLowerCase()))
      .map((name) => ({ value: name, label: `${name} (0)` }));
    return [
      ...offered.map((o) => ({ value: o.name, label: `${o.name} (${o.count})` })),
      ...stranded,
    ];
  }, [data?.market_options, contractTypes]);
  const narrowed = Boolean(
    q || sport || league || scope !== "all" || marketGroup || contractTypes.length || kickoffFrom || kickoffTo,
  );

  return (
    <div>
      <PageHeader
        title="Missing symbols"
        description="Upstream catalogue rows with no market_mapping stamp for the selected platform. Not RFQ demand."
      >
        <RefreshButton
          busy={isFetching}
          onClick={() => {
            setRefresh(true);
            void refetch();
          }}
        />
      </PageHeader>
      {data?.bq_project === "local" && data.local_path ? (
        <p className="mb-2 text-xs text-slate-500">
          Local snapshot: <span className="font-mono">{data.local_path}</span>
        </p>
      ) : null}
      {cacheNote ? <p className="mb-2 text-xs text-slate-500">{cacheNote}</p> : null}
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1">
          <label className="label" htmlFor="missing-q">
            Search
          </label>
          <input
            id="missing-q"
            className="input w-full"
            placeholder={
              showNxColumn
                ? "Symbol, fixture, or NX league token"
                : "Symbol or fixture"
            }
            value={q}
            onChange={(e) => {
              patchFilters({ q: e.target.value }, { replace: true });
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="missing-platform">
            Platform
          </label>
          <select
            id="missing-platform"
            className="input w-44"
            value={platform}
            onChange={(e) => {
              patchFilters({ platform: e.target.value });
            }}
          >
            {platformOptions.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
                {!row.missing_catalogue ? " (not wired)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="missing-scope">
            Scope
          </label>
          <select
            id="missing-scope"
            className="input w-44"
            value={scope}
            onChange={(e) => {
              patchFilters({ scope: e.target.value as MissingQueryState["scope"] });
            }}
          >
            {SCOPES.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="missing-sport">
            Sport
          </label>
          <select
            id="missing-sport"
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
          <label className="label" htmlFor="missing-league">
            League
          </label>
          <select
            id="missing-league"
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
          <label className="label" htmlFor="missing-market-group">
            Market group
          </label>
          <input
            id="missing-market-group"
            className="input w-40"
            placeholder="e.g. Player Prop"
            value={marketGroup}
            onChange={(e) => {
              patchFilters({ marketGroup: e.target.value }, { replace: true });
            }}
          />
        </div>
        <MultiSelect
          id="missing-markets"
          label="Markets"
          options={marketOptions}
          values={contractTypes}
          onChange={(next) => {
            patchFilters({ contractTypes: next });
          }}
          searchable
        />
        <div>
          <label className="label" htmlFor="missing-from">
            Kickoff from (UTC)
          </label>
          <input
            id="missing-from"
            type="datetime-local"
            className="input w-52"
            value={kickoffFrom}
            max={kickoffTo || undefined}
            onChange={(e) => {
              patchFilters({ kickoffFrom: e.target.value }, { replace: true });
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="missing-to">
            Kickoff to (UTC)
          </label>
          <input
            id="missing-to"
            type="datetime-local"
            className="input w-52"
            value={kickoffTo}
            min={kickoffFrom || undefined}
            onChange={(e) => {
              patchFilters({ kickoffTo: e.target.value }, { replace: true });
            }}
          />
        </div>
        {kickoffFrom || kickoffTo ? (
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={() => {
              patchFilters({ kickoffFrom: "", kickoffTo: "" });
            }}
          >
            Clear window
          </button>
        ) : null}
      </div>
      {data?.error ? <p className="mb-2 text-sm text-red-600">{data.error}</p> : null}
      {!isLoading && data && data.count === 0 && !data.error && narrowed ? (
        <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">
          No missing symbols match these filters.
        </p>
      ) : null}
      {!isLoading && data && data.count === 0 && !data.error && !narrowed ? (
        <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">
          No catalogue rows in the 21-day window for project{" "}
          <span className="font-mono">{data.bq_project ?? "unknown"}</span>. Restart the API via{" "}
          <span className="font-mono">scripts/start-console-local.ps1</span> (sets{" "}
          <span className="font-mono">MAPPING_MISSING_BQ_PROJECT=rs-marketmaking</span>) or check
          ADC access to prod BigQuery.
        </p>
      ) : null}
      <div className="card relative min-h-[14rem] overflow-x-auto p-0">
        <TableFetchOverlay active={isFetching} label="Loading catalogue…" />
        <table
          className={`w-full text-left text-xs ${isFetching ? "opacity-60" : ""}`}
          aria-busy={isFetching}
        >
          <thead className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
            <tr>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Fixture</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Scope</th>
              {showNxColumn ? <th className="px-3 py-2">NX</th> : null}
              <th className="px-3 py-2">League</th>
              <th className="px-3 py-2">Platform</th>
              <SortTh column="kickoff" label="Kickoff" sort={sort} dir={dir} onSort={onSort} />
              <th className="px-3 py-2 w-16" />
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((row) => {
              const rowKey = `${row.platform}:${row.symbol}`;
              const isExpanded = expandedKey === rowKey;
              const colSpan = showNxColumn ? 9 : 8;
              return (
                <Fragment key={rowKey}>
                  <tr className="border-b border-slate-100 dark:border-slate-800">
                    <td className="px-3 py-2 font-mono text-[11px]">{row.symbol}</td>
                    <td className="px-3 py-2">{row.fixture_name || "—"}</td>
                    <td className="px-3 py-2">
                      {row.market_group}
                      {row.contract_type ? ` / ${row.contract_type}` : ""}
                      {row.period_type ? ` @ ${row.period_type}` : ""}
                    </td>
                    <td className="px-3 py-2">{missingScopeLabel(row.scope)}</td>
                    {showNxColumn ? (
                      <td className="px-3 py-2">{row.crypto_prefix || "—"}</td>
                    ) : null}
                    <td className="px-3 py-2">{row.league || "—"}</td>
                    <td className="px-3 py-2">{platformLabel(explorePlatforms, row.platform)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {formatFixtureStart(row.kickoff)}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="btn-ghost text-xs"
                        aria-expanded={isExpanded}
                        onClick={() => setExpandedKey(isExpanded ? null : rowKey)}
                      >
                        Why
                      </button>
                    </td>
                  </tr>
                  {isExpanded ? (
                    <tr className="border-b border-slate-100 dark:border-slate-800">
                      <td className="px-3 py-3" colSpan={colSpan}>
                        <UnmappedRowWhy row={missingRowToUnmapped(row)} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        <RulesPager
          count={data?.count ?? 0}
          page={page}
          pageSize={pageSize}
          onPage={(nextPage) => {
            setExpandedKey(null);
            patchFilters({ page: nextPage });
          }}
          onPageSize={(nextLimit) => {
            patchFilters({ limit: nextLimit, page: 0 });
          }}
        />
      </div>
    </div>
  );
}
