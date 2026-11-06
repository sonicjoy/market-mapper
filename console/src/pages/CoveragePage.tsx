import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";

import { getCoverageFixture, listCoverageFixtures, searchRules } from "../api";
import { CoverageChip } from "../components/CoverageChip";
import { CoverageMarketPanel } from "../components/CoverageMarketPanel";
import { CoverageTeamCard } from "../components/CoverageTeamCard";
import { ExplorerShell } from "../components/ExplorerShell";
import { FixturePhaseTabs } from "../components/FixturePhaseTabs";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import { publishConsoleView } from "../consoleView";
import {
  COVERAGE_PAGE_SIZE,
  formatFixtureStart,
  lastPageIndex,
  readCoverageQuery,
  writeCoverageQuery,
} from "../lib/coverageList";
import { formatOpticTtko } from "../lib/proposedRail";
import type { CoverageFixture } from "../types";
import { usePageFilters } from "../usePageFilters";

export function CoveragePage() {
  const [params, setParams] = usePageFilters("coverage");
  const { league, fixture, sport, q: fixtureName, phase, page } = readCoverageQuery(params);
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
    queryKey: ["coverage", league, sport, fixtureName, phase, page],
    queryFn: () =>
      listCoverageFixtures({
        league: league || undefined,
        sport: sport || undefined,
        q: fixtureName.trim() || undefined,
        phase,
        limit: COVERAGE_PAGE_SIZE,
        offset: page * COVERAGE_PAGE_SIZE,
      }),
  });

  const detail = useQuery({
    queryKey: ["coverage", "detail", fixture],
    queryFn: () => getCoverageFixture(fixture),
    enabled: Boolean(fixture),
  });

  const count = data?.count ?? 0;
  const listReady = data != null && !isLoading;
  const lastPage = lastPageIndex(count, COVERAGE_PAGE_SIZE);
  const safePage = listReady ? Math.min(page, lastPage) : page;
  const pageItems = data?.fixtures ?? [];

  const setCoveragePage = useCallback(
    (nextPage: number) => {
      setParams(writeCoverageQuery(params, { page: Math.max(0, nextPage) }));
    },
    [params, setParams],
  );

  useEffect(() => {
    publishConsoleView({
      path: "/coverage",
      coverage: { league, sport, fixture, q: fixtureName },
    });
  }, [league, sport, fixture, fixtureName]);

  useEffect(() => {
    if (!listReady) return;
    if (page !== safePage) setCoveragePage(safePage);
  }, [listReady, page, safePage, setCoveragePage]);

  function patchFilters(
    patch: Parameters<typeof writeCoverageQuery>[1],
    opts?: { replace?: boolean },
  ) {
    setParams(writeCoverageQuery(params, { page: 0, ...patch }), opts);
  }

  return (
    <div>
      <PageHeader
        title="Coverage"
        description="Published stamps vs tip market types (0 means unpublished, not missing rules). Live/pre tabs use Optic status (kickoff when status is missing)."
      >
        <RefreshButton busy={isFetching} onClick={() => void refetch()} />
      </PageHeader>
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="coverage-sport">
            Sport
          </label>
          <select
            id="coverage-sport"
            className="input w-44"
            value={sport}
            onChange={(e) => {
              const nextSport = e.target.value;
              const current = tipLeagues.find((row) => row.league === league);
              const leagueGone = Boolean(league && nextSport && current?.sport !== nextSport);
              patchFilters({
                sport: nextSport,
                league: leagueGone ? "" : league,
                fixture: "",
              });
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
          <label className="label" htmlFor="coverage-league">
            League
          </label>
          <select
            id="coverage-league"
            className="input w-56"
            value={league}
            onChange={(e) => {
              patchFilters({ league: e.target.value, fixture: "" });
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
        <div className="min-w-[12rem] flex-1">
          <label className="label" htmlFor="coverage-fixture-name">
            Fixture
          </label>
          <input
            id="coverage-fixture-name"
            className="input w-full"
            placeholder="Filter by name"
            value={fixtureName}
            onChange={(e) => {
              patchFilters({ q: e.target.value }, { replace: true });
            }}
          />
        </div>
      </div>
      <ExplorerShell
        list={
          <div className="space-y-1">
            <FixturePhaseTabs
              phase={phase}
              onChange={(nextPhase) => {
                patchFilters({ phase: nextPhase, fixture: "", page: 0 });
              }}
            />
            {isLoading ? (
              <p className="px-2 py-4 text-xs text-slate-500">Loading fixtures…</p>
            ) : pageItems.length === 0 ? (
              <p className="px-2 py-4 text-xs text-slate-500">No fixtures match.</p>
            ) : (
              pageItems.map((fx) => (
                <button
                  key={fx.fixture_id}
                  type="button"
                  className={`flex w-full items-center justify-between rounded px-2 py-2 text-left text-xs ${
                    fixture === fx.fixture_id
                      ? "bg-brand-50 font-medium dark:bg-brand-950/50"
                      : "hover:bg-slate-50 dark:hover:bg-slate-800"
                  }`}
                  onClick={() => {
                    setParams(writeCoverageQuery(params, { fixture: fx.fixture_id }));
                  }}
                >
                  <span>
                    <div>{fx.label}</div>
                    <div className="text-slate-500">
                      {[
                        fx.sport,
                        fx.league_label || fx.league,
                        formatOpticTtko(fx.optic_status, fx.ttko_hours),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </span>
                  <CoverageChip
                    mapped={fx.coverage?.mapped_count ?? 0}
                    expected={fx.coverage?.expected_count ?? 0}
                  />
                </button>
              ))
            )}
          </div>
        }
        listFooter={
          <CoverageListPager
            count={count}
            page={safePage}
            onPage={setCoveragePage}
          />
        }
        detail={
          fixture ? (
            detail.isLoading ? (
              <p className="text-sm text-slate-500">Loading fixture coverage…</p>
            ) : detail.isError ? (
              <p className="text-sm text-red-600">
                Could not load fixture coverage{detail.error?.message ? `: ${detail.error.message}` : "."}
              </p>
            ) : detail.data ? (
              <CoverageDetail fixture={detail.data} disclaimer={data?.disclaimer} />
            ) : (
              <p className="text-sm text-slate-500">Fixture not found.</p>
            )
          ) : (
            <p className="text-sm text-slate-500">Select a fixture to inspect coverage.</p>
          )
        }
      />
    </div>
  );
}

function CoverageListPager({
  count,
  page,
  onPage,
}: {
  count: number;
  page: number;
  onPage: (page: number) => void;
}) {
  if (count === 0) return null;
  const from = page * COVERAGE_PAGE_SIZE + 1;
  const to = Math.min(count, (page + 1) * COVERAGE_PAGE_SIZE);
  const last = lastPageIndex(count, COVERAGE_PAGE_SIZE);
  return (
    <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-2 py-2 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300">
      <span>
        {from}–{to} of {count}
      </span>
      <div className="flex gap-1">
        <button
          type="button"
          className="btn-ghost"
          disabled={page <= 0}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={page >= last}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function CoverageDetail({
  fixture,
  disclaimer,
}: {
  fixture: CoverageFixture;
  disclaimer?: string;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">{fixture.label}</h2>
        <p className="text-xs text-slate-500">
          {[fixture.sport, fixture.league_label || fixture.league].filter(Boolean).join(" · ") ||
            "Sport/league unknown"}
        </p>
        <p className="text-xs text-slate-500">
          {[
            formatFixtureStart(fixture.start_date),
            formatOpticTtko(fixture.optic_status, fixture.ttko_hours),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <p className="text-xs text-slate-500">{disclaimer}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <CoverageTeamCard
          side="home"
          name={fixture.home || ""}
          league={fixture.league}
          entity={fixture.home_entity}
          matchEntityType={fixture.league_entity_type}
          opticId={fixture.home_competitor_ids?.[0]}
          opticAbbr={fixture.home_abbr}
        />
        <CoverageTeamCard
          side="away"
          name={fixture.away || ""}
          league={fixture.league}
          entity={fixture.away_entity}
          matchEntityType={fixture.league_entity_type}
          opticId={fixture.away_competitor_ids?.[0]}
          opticAbbr={fixture.away_abbr}
        />
      </div>
      <CoverageMarketPanel fixture={fixture} />
    </div>
  );
}
