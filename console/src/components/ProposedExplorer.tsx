import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { trimProposedItems } from "../api";
import { ExplorerShell } from "./ExplorerShell";
import { MappingRowCard } from "./MappingRow";
import { formatFixtureStart } from "../lib/coverageList";
import { isGatewayDrop } from "../lib/gatewayDrop";
import type { ProposedLeagueBlock, ProposedView } from "../types";
import {
  KIND_FILTERS,
  approveCount,
  dropsForApprove,
  fixtureRfqVolume,
  formatRailMeta,
  formatTtko,
  guessPending,
  leagueRows,
  markDrop,
  markKeep,
  otherLeagueScope,
  parseKindFilter,
  pickVisibleLeague,
  rowsForKind,
  rowsForSelection,
  rowsHidingOptic,
  showsFixtures,
  visibleLeaguePills,
  type ProposedKindFilter,
  type RailSelection,
} from "../lib/proposedRail";
import { isOpticMapping } from "../lib/mappingDisplay";
import {
  clearProposedViewState,
  hydrateProposedSearchParams,
  proposedReturnPath,
  readProposedViewState,
  writeProposedViewState,
} from "../lib/proposedViewState";
import { nextApproveAfterTrim, supersededByRef } from "../lib/reviewQueue";

type Props = {
  proposalRef: string;
  proposed: ProposedView;
  allRows: ProposedLeagueBlock["rows"];
  waiting: boolean;
  validating?: boolean;
  onTrimmed: () => void;
  onApprove: () => void;
  approvePending?: boolean;
  comment: string;
  onComment: (value: string) => void;
  onReject: () => void;
  rejectPending?: boolean;
  onWaitThenApprove?: () => void;
};

export function ProposedExplorer({
  proposalRef,
  proposed,
  allRows,
  waiting,
  validating,
  onTrimmed,
  onApprove,
  approvePending,
  comment,
  onComment,
  onReject,
  rejectPending,
  onWaitThenApprove,
}: Props) {
  const [params, setParams] = useSearchParams();
  const saved = useMemo(() => readProposedViewState(proposalRef), [proposalRef]);
  const [kept, setKept] = useState<Set<string>>(() => new Set(saved?.kept ?? []));
  const [trimError, setTrimError] = useState("");
  const [hideOptic, setHideOptic] = useState(() => saved?.hideOptic ?? false);
  const [trimming, setTrimming] = useState(false);
  const pageRef = useRef<HTMLDivElement>(null);
  const hydratedRail = useRef(false);
  const urlHasRail = Boolean(params.get("league") || params.get("kind") || params.get("fixture"));
  const applySavedRail = Boolean(saved && !urlHasRail);
  const kind = parseKindFilter(
    params.get("kind") ?? (applySavedRail && saved && saved.kind !== "all" ? saved.kind : null),
  );
  const requestedLeague = params.get("league") || (applySavedRail ? saved?.league : "") || "";
  const pills = visibleLeaguePills(proposed.leagues, allRows, kind, hideOptic);
  const activeLeague = pickVisibleLeague(pills, requestedLeague);
  const block = proposed.leagues.find((b) => b.league === activeLeague) ?? proposed.leagues[0];
  const league = block?.league ?? "";
  const fixtureRaw =
    params.get("fixture") ||
    (applySavedRail && showsFixtures(kind) && saved?.league === league ? saved?.fixture : "") ||
    "";
  const fixture =
    block &&
    block.fixtures.some((fx) => fx.fixture_id === fixtureRaw) &&
    rowsHidingOptic(
      rowsForKind(
        rowsForSelection(
          block,
          { type: "fixture", league: block.league, fixtureId: fixtureRaw },
          allRows,
        ),
        kind,
      ),
      hideOptic,
    ).length > 0
      ? fixtureRaw
      : "";
  const selection: RailSelection = fixture
    ? { type: "fixture", league: block?.league ?? league, fixtureId: fixture }
    : { type: "league", league: block?.league ?? league };

  const visibleRows = useMemo(() => {
    if (!block) return [];
    const useLeagueScope = kind === "market_rule" || kind === "league" || !fixture;
    const sel: RailSelection = useLeagueScope
      ? { type: "league", league: block.league }
      : { type: "fixture", league: block.league, fixtureId: fixture };
    return rowsHidingOptic(rowsForKind(rowsForSelection(block, sel, allRows), kind), hideOptic);
  }, [allRows, block, fixture, hideOptic, kind]);
  const allLeagueRows = useMemo(
    () => (block ? leagueRows(block, allRows) : []),
    [allRows, block],
  );
  const shownLeagueRows = useMemo(
    () => rowsHidingOptic(rowsForKind(allLeagueRows, kind), hideOptic),
    [allLeagueRows, hideOptic, kind],
  );
  const opticCount = useMemo(() => allRows.filter(isOpticMapping).length, [allRows]);

  const setRail = (nextLeague: string, nextFixture?: string) => {
    const next = new URLSearchParams(params);
    next.set("league", nextLeague);
    if (nextFixture) next.set("fixture", nextFixture);
    else next.delete("fixture");
    setParams(next);
  };

  const setKind = (nextKind: ProposedKindFilter) => {
    const next = new URLSearchParams(params);
    if (nextKind === "all") next.delete("kind");
    else next.set("kind", nextKind);
    if (nextKind === "market_rule" || nextKind === "league") next.delete("fixture");
    setParams(next);
  };

  useEffect(() => {
    if (hydratedRail.current) return;
    hydratedRail.current = true;
    const patched = hydrateProposedSearchParams(params, saved);
    if (patched) setParams(patched, { replace: true });
  }, [params, saved, setParams]);

  useEffect(() => {
    if (!waiting && !validating) {
      clearProposedViewState(proposalRef);
      return;
    }
    writeProposedViewState(proposalRef, {
      league,
      fixture,
      kind,
      hideOptic,
      kept: [...kept],
    });
  }, [proposalRef, league, fixture, kind, hideOptic, kept, waiting, validating]);

  const scrollToTop = () => {
    const main = pageRef.current?.closest("main");
    if (main instanceof HTMLElement) {
      main.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const dropRow = (key: string) => {
    setTrimError("");
    setKept((prev) => markDrop(prev, key));
  };

  const keepRow = (key: string) => {
    setKept((prev) => markKeep(prev, key));
  };

  const approve = async () => {
    setTrimError("");
    const drops = dropsForApprove(allRows, kept);
    if (!drops.length) {
      onApprove();
      return;
    }
    setTrimming(true);
    try {
      const view = await trimProposedItems(proposalRef, drops);
      onTrimmed();
      if (view.status === "rejected") return;
      if (nextApproveAfterTrim(view.status) === "approve") {
        onApprove();
        return;
      }
      onWaitThenApprove?.();
    } catch (err) {
      if (isGatewayDrop(err)) {
        onTrimmed();
        onWaitThenApprove?.();
        return;
      }
      setTrimError(err instanceof Error ? err.message : "Could not drop pins before approve");
      onTrimmed();
    } finally {
      setTrimming(false);
    }
  };

  if (!block) {
    return <p className="text-sm text-slate-500">No league blocks in this proposal.</p>;
  }

  const total = approveCount(allRows, kept);
  const guesses = guessPending(allRows, kept);
  const scope = otherLeagueScope(allRows, block.league, kept);
  const selectedFixture =
    showsFixtures(kind) && selection.type === "fixture"
      ? block.fixtures.find((fx) => fx.fixture_id === selection.fixtureId)
      : undefined;
  const selectedRfq = selectedFixture
    ? fixtureRfqVolume(
        selectedFixture,
        rowsForSelection(
          block,
          { type: "fixture", league: block.league, fixtureId: selectedFixture.fixture_id },
          allRows,
        ),
      )
    : 0;
  const liveRef = supersededByRef(trimError);

  return (
    <div ref={pageRef} className="space-y-3">
      <div
        role="tablist"
        aria-label="Proposed change kind"
        className="flex flex-wrap gap-1"
      >
        {KIND_FILTERS.map((item) => {
          const n = rowsForKind(allRows, item.id).length;
          const active = kind === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={`rounded-full border px-2.5 py-1 text-xs ${
                active
                  ? "border-brand-600 bg-brand-50 font-medium text-brand-800 dark:border-brand-400 dark:bg-brand-950/50 dark:text-brand-200"
                  : "border-slate-200 text-slate-600 hover:border-slate-400 dark:border-slate-700 dark:text-slate-300"
              }`}
              onClick={() => setKind(item.id)}
            >
              {item.label}
              <span className="ml-1 text-slate-400">{n}</span>
            </button>
          );
        })}
      </div>
      <ExplorerShell
        pills={pills}
        activePill={block.league}
        onPill={(id) => setRail(id)}
        list={
          <div className="space-y-1">
            <button
              type="button"
              className={`block w-full rounded px-2 py-2 text-left text-xs ${
                selection.type === "league"
                  ? "bg-brand-50 font-medium text-brand-800 dark:bg-brand-950/50 dark:text-brand-200"
                  : "hover:bg-slate-50 dark:hover:bg-slate-800"
              }`}
              onClick={() => setRail(block.league)}
            >
              <div className="font-semibold">All proposed changes</div>
              <div className="text-slate-500">
                {shownLeagueRows.length} pin{shownLeagueRows.length === 1 ? "" : "s"} in {block.league_label}
              </div>
            </button>
            {showsFixtures(kind)
              ? block.fixtures.flatMap((fx) => {
                  const related = rowsHidingOptic(
                    rowsForKind(
                      rowsForSelection(
                        block,
                        { type: "fixture", league: block.league, fixtureId: fx.fixture_id },
                        allRows,
                      ),
                      kind,
                    ),
                    hideOptic,
                  );
                  if (related.length === 0) return [];
                  return [
                    <button
                      key={fx.fixture_id}
                      type="button"
                      className={`block w-full rounded px-2 py-2 text-left text-xs ${
                        selection.type === "fixture" && selection.fixtureId === fx.fixture_id
                          ? "bg-brand-50 font-medium text-brand-800 dark:bg-brand-950/50 dark:text-brand-200"
                          : "hover:bg-slate-50 dark:hover:bg-slate-800"
                      }`}
                      onClick={() => setRail(block.league, fx.fixture_id)}
                    >
                      <div>{fx.label}</div>
                      <div className="text-slate-500">
                        {formatRailMeta(fx.ttko_hours, fixtureRfqVolume(fx, related), related.length)}
                      </div>
                    </button>,
                  ];
                })
              : null}
          </div>
        }
        detail={
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold">
                {selectedFixture
                  ? selectedFixture.label
                  : `All proposed changes — ${block.league_label}`}
                {selectedFixture ? (
                  <span className="ml-2 font-normal text-slate-500">
                    {formatFixtureStart(selectedFixture.start_date)}
                    {selectedFixture.ttko_hours != null
                      ? ` · ${formatTtko(selectedFixture.ttko_hours)}`
                      : ""}
                    {selectedRfq > 0 ? ` · ${selectedRfq} RFQ` : ""}
                  </span>
                ) : null}
              </h3>
              <p className="text-xs text-slate-500">
                {kind === "market_rule"
                  ? "Showing market-rule pins in this league, including cloned taxonomies. Approve still covers the whole proposal."
                  : kind === "league"
                    ? "Showing league pins in this league. Approve still covers the whole proposal."
                    : kind === "ai"
                      ? "Showing AI guesses. Click a fixture to filter. Approve still covers the whole proposal."
                      : kind === "alias"
                        ? "Showing alias pins. Click a fixture to filter. Approve still covers the whole proposal."
                        : selection.type === "fixture"
                          ? "Showing pins related to this fixture. Approve still covers the whole proposal."
                          : "Showing every pin in this league. Click a fixture to filter, or use Market rules to jump to cloned taxonomies."}
              </p>
            </div>
            {visibleRows.map((row) => (
              <MappingRowCard
                key={row.key}
                row={row}
                kept={kept}
                onKeep={keepRow}
                onDrop={dropRow}
                returnTo={proposedReturnPath(proposalRef, { league: block.league, fixture, kind })}
              />
            ))}
            {visibleRows.length === 0 ? (
              <p className="text-sm text-slate-500">
                {kind === "market_rule"
                  ? "No market rules in this league. Pick a league whose Market rules count is above zero — cloned taxonomies sit on new-league pins."
                  : kind === "ai"
                    ? "No AI guesses in this league."
                    : hideOptic && opticCount > 0
                      ? "No non-Optic rows for this selection."
                      : "No rows for this selection."}
              </p>
            ) : null}
          </div>
        }
      />
      {waiting || validating || trimming || trimError ? (
        <div className="sticky bottom-0 z-10 space-y-2 rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs text-slate-600 dark:text-slate-300">
              Approve proposal ({total} items)
              {guesses > 0 ? ` · ${guesses} AI guess${guesses === 1 ? "" : "es"} set to Drop` : ""}
              {hideOptic && opticCount > 0 ? ` · ${opticCount} Optic pins hidden (still in Approve)` : ""}
              {scope}
            </div>
            <button type="button" className="btn-ghost shrink-0 text-xs" onClick={scrollToTop}>
              Return to top
            </button>
          </div>
          {opticCount > 0 ? (
            <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
              <input
                type="checkbox"
                checked={hideOptic}
                onChange={(e) => setHideOptic(e.target.checked)}
              />
              Hide Optic mappings
              <span className="text-slate-400">({opticCount})</span>
            </label>
          ) : null}
          {trimError ? (
            <p className="text-sm text-red-600">
              {trimError}
              {liveRef ? (
                <>
                  {" "}
                  <Link to={`/review/${liveRef}`} className="font-medium underline">
                    Open the new card
                  </Link>
                </>
              ) : null}
            </p>
          ) : null}
          {trimming || (validating && !trimError) ? (
            <p className="text-xs text-slate-500">
              {trimming ? "Dropping pins and re-validating…" : "Re-validating after Drop…"}
            </p>
          ) : null}
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[12rem] flex-1">
              <label className="label" htmlFor="comment">
                Comment
              </label>
              <input
                id="comment"
                className="input"
                value={comment}
                onChange={(e) => onComment(e.target.value)}
                placeholder="Optional comment for reject"
              />
            </div>
            <button
              type="button"
              className="btn-ghost shrink-0"
              disabled={rejectPending || trimming}
              onClick={onReject}
            >
              Reject
            </button>
            <button
              type="button"
              className="btn-primary shrink-0"
              disabled={
                Boolean(approvePending) || trimming || (Boolean(validating) && !waiting && !trimError)
              }
              onClick={() => void approve()}
            >
              Approve proposal ({total} items)
            </button>
          </div>
        </div>
      ) : null}
      <p className="text-xs text-slate-500">
        <Link to="/review">← All proposals</Link>
      </p>
    </div>
  );
}
