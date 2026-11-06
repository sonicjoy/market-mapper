import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { searchRules } from "../api";
import { EntitiesTable } from "../components/EntitiesTable";
import { MarketRulesTable } from "../components/MarketRulesTable";
import { PageHeader } from "../components/PageHeader";
import { RulesFilters } from "../components/RulesFilters";
import { RulesPager } from "../components/RulesPager";
import { SortTh } from "../components/SortTh";
import { publishRulesView } from "../consoleView";
import { BOOK_CHIP_BASE, bookChipClass, bookChipTitle, leagueBookSlots } from "../lib/leagueBooks";
import { nextSort, readRulesQuery, writeRulesQuery } from "../lib/rulesQuery";
import type {
  EntityAliasPin,
  EntityRuleRow,
  EntryLocationState,
  LeagueExchange,
  LeagueRuleRow,
  MarketRuleRow,
} from "../types";
import { usePageFilters } from "../usePageFilters";
import { useTipLeagues } from "../useTipLeagues";

type Kind = "entities" | "leagues" | "market_rules";

/** Best-effort machine key when API only returned a display label. */
function leagueKey(row: { league?: string; league_label?: string }): string {
  if (row.league?.trim()) return row.league.trim();
  const label = row.league_label?.trim();
  if (!label) return "";
  return label.toLowerCase().replace(/\s+/g, "_");
}

function bookKey(row: { sportsbook?: string; sportsbook_label?: string }): string {
  return (row.sportsbook || row.sportsbook_label || "").trim();
}

/** Known books always shown; dashed = absent from the league, strike = disabled pin. */
function BookChips({ exchanges }: { exchanges: LeagueExchange[] }) {
  const chips = leagueBookSlots(exchanges);
  return (
    <span className="flex flex-wrap gap-1">
      {chips.map((chip) => (
        <span
          key={chip.sportsbook}
          title={bookChipTitle(chip)}
          className={`cursor-help ${BOOK_CHIP_BASE} ${bookChipClass(chip)}`}
        >
          {chip.sportsbook}
        </span>
      ))}
    </span>
  );
}

const KINDS: { id: Kind; label: string }[] = [
  { id: "market_rules", label: "Market rules" },
  { id: "entities", label: "Entities" },
  { id: "leagues", label: "Leagues" },
];

function ProposeBtn({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn-ghost text-xs" onClick={onClick}>
      Propose change
    </button>
  );
}

export function RulesPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = usePageFilters("rules");
  const query = readRulesQuery(searchParams);
  const { kind, page, limit, league, sportsbook, canonical, action, sort, dir } = query;
  const submitted = query.q;
  const [draft, setDraft] = useState(submitted);
  const tipLeagues = useTipLeagues();
  const leagueOptions = (tipLeagues.data ?? []).map((slug) => ({
    value: slug,
    label: slug.replace(/_/g, " "),
  }));

  useEffect(() => {
    setDraft(submitted);
  }, [submitted]);

  useEffect(() => {
    publishRulesView({
      kind,
      q: submitted,
      league,
      sportsbook,
      canonical,
      action,
      sort,
      dir,
      page,
      limit,
    });
  }, [kind, submitted, league, sportsbook, canonical, action, sort, dir, page, limit]);

  function patchParams(patch: Parameters<typeof writeRulesQuery>[1]) {
    setSearchParams(writeRulesQuery(searchParams, patch));
  }

  function onSort(column: string) {
    patchParams(nextSort(sort, dir, column));
  }

  const { data, isFetching, isError, error } = useQuery({
    queryKey: ["rules", submitted, kind, page, limit, league, sportsbook, canonical, action, sort, dir],
    queryFn: () =>
      searchRules(submitted, kind, {
        limit,
        offset: page * limit,
        league,
        sportsbook,
        canonical: kind === "market_rules" ? canonical : undefined,
        action: kind === "market_rules" ? action : undefined,
        sort: sort || undefined,
        dir: sort ? dir : undefined,
      }),
    // Keep the current page visible while a filter/sort/page change refetches.
    placeholderData: keepPreviousData,
  });

  function goEntry(state: EntryLocationState) {
    void navigate("/entry", { state: { ...state, fromRules: true } });
  }

  function proposeEntity(row: EntityRuleRow, pin: EntityAliasPin) {
    const sportsbook = bookKey(pin);
    const league = leagueKey(row);
    const code = (pin.code || "").trim();
    if (!league || !sportsbook || !code) {
      window.alert(
        "This row is missing league, sportsbook, or code. Search again after refreshing the page.",
      );
      return;
    }
    goEntry({
      tab: "alias",
      mode: "amend",
      league,
      sportsbook,
      code,
      entity_name: row.entity_name || "",
      entity_type: row.entity_type || "team",
      canonical_key: row.canonical_key || "",
      alias_kind: pin.alias_kind || "code",
      note: `From Rules: ${sportsbook} ${code}`,
    });
  }

  function removeEntity(row: EntityRuleRow, pin: EntityAliasPin) {
    const sportsbook = bookKey(pin);
    const league = leagueKey(row);
    const code = (pin.code || "").trim();
    if (!league || !sportsbook || !code) {
      window.alert(
        "This row is missing league, sportsbook, or code. Search again after refreshing the page.",
      );
      return;
    }
    goEntry({
      tab: "alias",
      mode: "remove",
      league,
      sportsbook,
      code,
      entity_name: row.entity_name || "",
      entity_type: row.entity_type || "team",
      canonical_key: row.canonical_key || "",
      alias_kind: pin.alias_kind || "code",
      note: `From Rules: remove ${sportsbook} ${code}`,
    });
  }

  function proposeLeague(row: LeagueRuleRow) {
    const league = leagueKey(row);
    if (!league) {
      window.alert("This league row is missing a league key. Search again after refreshing.");
      return;
    }
    goEntry({
      tab: "league",
      league,
      sport: row.sport || "",
      optic_league_id: row.optic_league_id || "",
      fixture_source: row.fixture_source || "api",
      fixture_horizon_hours: row.fixture_horizon_hours,
      enabled: row.enabled,
      exchanges: row.exchanges ?? [],
      note: `From Rules: update ${league}`,
    });
  }

  function proposeMarket(row: MarketRuleRow) {
    const sportsbook = bookKey(row);
    const league = leagueKey(row);
    if (!league || !sportsbook) {
      window.alert(
        "This market-rule row is missing league or sportsbook. Search again after refreshing.",
      );
      return;
    }
    goEntry({
      tab: "market",
      league,
      sportsbook,
      source_key: row.source_key || "",
      action: row.action || "map",
      canonical_market_type: row.canonical_market_type,
      source_key_type: row.source_key_type || undefined,
      match_operator: row.match_operator,
      line_offset: row.line_offset ?? null,
      yes_side: row.yes_side ?? null,
      side_swap: row.side_swap ?? null,
      official_description: row.official_description ?? null,
      citation_url: row.citation_url ?? null,
      note: row.notes ?? "",
    });
  }

  return (
    <div>
      <PageHeader
        title="Rules"
        description="Search current mapping aliases, leagues, or market rules. Propose change opens Editor pre-filled. On Market rules, select ignored rows to enable or mapped rows to ignore, then add to cart."
      />

      <div className="mb-4 flex gap-1 border-b border-slate-200 dark:border-slate-700">
        {KINDS.map((k) => (
          <button
            key={k.id}
            type="button"
            className={`px-3 py-1.5 text-sm ${
              kind === k.id
                ? "border-b-2 border-brand-600 font-medium text-brand-800 dark:text-brand-200"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            }`}
            onClick={() => patchParams({ kind: k.id, q: draft.trim(), page: 0, sort: "", dir: "asc" })}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <form
          className="flex min-w-[12rem] max-w-sm flex-[1_1_12rem] gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            patchParams({ q: draft.trim(), page: 0 });
          }}
        >
          <input
            className="input min-w-0"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. M05, Mainz, Optic"
          />
          <button type="submit" className="btn-primary shrink-0">
            Search
          </button>
        </form>
        <RulesFilters
          kind={kind}
          league={league}
          sportsbook={sportsbook}
          canonical={canonical}
          action={action}
          leagueOptions={leagueOptions}
          onChange={patchParams}
        />
      </div>
      {isFetching && <p className="text-sm text-slate-500 dark:text-slate-400">Searching…</p>}
      {isError && (
        <p className="text-sm text-red-600">{error instanceof Error ? error.message : "Search failed."}</p>
      )}
      {data && kind === "entities" && (
        <EntitiesTable
          rows={data.entities ?? []}
          count={data.count}
          page={page}
          pageSize={limit}
          sort={sort}
          dir={dir}
          onSort={onSort}
          onPropose={proposeEntity}
          onRemove={removeEntity}
          onPage={(p) => patchParams({ page: p })}
          onPageSize={(size) => patchParams({ limit: size, page: 0 })}
        />
      )}
      {data && kind === "leagues" && (
        <div className="panel">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <SortTh column="league" label="League" sort={sort} dir={dir} onSort={onSort} />
                <SortTh column="sport" label="Sport" sort={sort} dir={dir} onSort={onSort} />
                <SortTh column="sportsbooks" label="Sportsbooks" sort={sort} dir={dir} onSort={onSort} />
                <SortTh column="optic_league_id" label="Optic id" sort={sort} dir={dir} onSort={onSort} />
                <SortTh column="fixture_source" label="Fixture source" sort={sort} dir={dir} onSort={onSort} />
                <SortTh column="enabled" label="Enabled" sort={sort} dir={dir} onSort={onSort} />
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {(data.leagues ?? []).map((row, i) => (
                <tr key={`${row.league}-${i}`} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2">{row.league_label}</td>
                  <td className="px-3 py-2">{row.sport}</td>
                  <td className="px-3 py-2">
                    <BookChips exchanges={row.exchanges ?? []} />
                  </td>
                  <td className="px-3 py-2 font-mono">{row.optic_league_id}</td>
                  <td className="px-3 py-2">{row.fixture_source}</td>
                  <td className="px-3 py-2">{row.enabled ? "yes" : "no"}</td>
                  <td className="px-3 py-2 text-right">
                    <ProposeBtn onClick={() => proposeLeague(row)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.count === 0 && <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">No matches.</p>}
          <RulesPager
            count={data.count}
            page={page}
            pageSize={limit}
            onPage={(p) => patchParams({ page: p })}
            onPageSize={(size) => patchParams({ limit: size, page: 0 })}
          />
        </div>
      )}
      {data && kind === "market_rules" && (
        <MarketRulesTable
          rows={data.market_rules ?? []}
          count={data.count}
          page={page}
          pageSize={limit}
          sort={sort}
          dir={dir}
          resetKey={`${submitted}|${limit}|${league.join(",")}|${sportsbook.join(",")}|${canonical.join(",")}|${action.join(",")}`}
          onPropose={proposeMarket}
          onPage={(p) => patchParams({ page: p })}
          onPageSize={(size) => patchParams({ limit: size, page: 0 })}
          onSort={onSort}
        />
      )}
    </div>
  );
}
