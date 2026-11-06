import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { addCartItem } from "../cartStore";
import { sportsbookLabel } from "../entryEnums";
import {
  baselineToggles,
  cellHasRule,
  cellSourceLabel,
  coverageCellKey,
  coverageGridAxes,
  coveragePlatformLabel,
  dirtyToggleKeys,
  coverageLeagueHeaderState,
  leaguePlatformEntryState,
  missingMarketEntryState,
  platformLeagueEnabled,
  rowsForToggleChanges,
  type CoverageCellKey,
  type CoverageLeagueDetail,
} from "../lib/coverageMarketGrid";
import {
  filterStampSections,
  formatStampUpdated,
  groupStampsByCanonical,
  nextStampInspectState,
  type StampFocus,
} from "../lib/coverageStamps";
import { BOOK_CHIP_BASE, bookChipClass } from "../lib/leagueBooks";
import { coverageToggleMessage, stageMarketRuleToggles } from "../lib/marketRules";
import type { CoverageFixture, CoverageStampRow, MarketRuleRow } from "../types";
import { BookChipToggle } from "./BookChipToggle";
import { CoverageChip } from "./CoverageChip";

const EMPTY_RULES: MarketRuleRow[] = [];
const EMPTY_STAMPS: CoverageStampRow[] = [];
const OPTIC_BOOK = "optic";

type Props = {
  fixture: CoverageFixture;
};

export function CoverageMarketPanel({ fixture }: Props) {
  const rules = fixture.market_rules ?? EMPTY_RULES;
  const stamps = fixture.coverage_detail?.stamps ?? EMPTY_STAMPS;
  const { markets, platforms } = useMemo(
    () => coverageGridAxes(rules, fixture.output_order ?? []),
    [rules, fixture.output_order],
  );
  const sections = useMemo(() => groupStampsByCanonical(stamps, markets), [stamps, markets]);
  const sectionsByCanonical = useMemo(
    () => new Map(sections.map((section) => [section.canonical, section])),
    [sections],
  );
  const baseline = useMemo(() => baselineToggles(rules), [rules]);
  const [toggles, setToggles] = useState<Record<CoverageCellKey, boolean>>(baseline);
  const [message, setMessage] = useState<string | null>(null);
  const [openCanonical, setOpenCanonical] = useState<string | null>(null);
  const [stampQuery, setStampQuery] = useState("");
  const [stampBook, setStampBook] = useState("");

  useEffect(() => {
    setToggles(baseline);
    setMessage(null);
    setOpenCanonical(null);
    setStampQuery("");
    setStampBook("");
  }, [baseline, fixture.fixture_id]);

  const filteredSections = useMemo(
    () => filterStampSections(sections, { book: stampBook, query: stampQuery }),
    [sections, stampBook, stampQuery],
  );
  const filteredByCanonical = useMemo(
    () => new Map(filteredSections.map((section) => [section.canonical, section])),
    [filteredSections],
  );
  const dirty = dirtyToggleKeys(baseline, toggles);
  const changeCount = dirty.length;
  const league = (fixture.league || "").trim();
  const leagueDetail = fixture.league_detail ?? null;
  const bookPlatforms = useMemo(
    () => platforms.filter((book) => book !== OPTIC_BOOK),
    [platforms],
  );
  const colSpan = bookPlatforms.length + 1;

  function setCell(key: CoverageCellKey, next: boolean) {
    setToggles((prev) => ({ ...prev, [key]: next }));
  }

  function stageChanges() {
    const { enableRows, disableRows } = rowsForToggleChanges(rules, baseline, toggles);
    const result = stageMarketRuleToggles(enableRows, disableRows);
    for (const item of result.cartItems) {
      addCartItem({ kind: "mapping_market_rules", label: item.label, payload: item.payload });
    }
    setMessage(coverageToggleMessage(result));
    if (result.stagedCount) setToggles(baseline);
  }

  function toggleCanonical(canonical: string) {
    setOpenCanonical((prev) => (prev === canonical ? null : canonical));
    setStampQuery("");
    setStampBook("");
  }

  function inspectStamps(focus: StampFocus) {
    const next = nextStampInspectState(
      { openCanonical, stampBook, stampQuery },
      focus,
    );
    setOpenCanonical(next.openCanonical);
    setStampBook(next.stampBook);
    setStampQuery(next.stampQuery);
  }

  return (
    <div id="coverage-stamps" className="panel">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-semibold uppercase text-slate-500">Market rules</h3>
            <CoverageChip
              mapped={fixture.coverage?.mapped_count ?? 0}
              expected={fixture.coverage?.expected_count ?? 0}
            />
          </div>
          <p className="text-[11px] text-slate-500">
            League-wide map/ignore. Expand a row for published{" "}
            <span className="font-mono">market_mapping</span> stamps. Empty cell: source key
            unknown — Add opens Editor.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={!changeCount}
          onClick={stageChanges}
        >
          Add to cart ({changeCount})
        </button>
      </div>
      {message ? (
        <p className="border-b border-slate-100 px-3 py-2 text-sm text-brand-800 dark:border-slate-800 dark:text-brand-200">
          {message}{" "}
          <Link className="underline" to="/cart">
            Open cart
          </Link>
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-50 text-[10px] uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2">
                <div className="flex flex-nowrap items-center gap-x-2">
                  <span>Optic canonical</span>
                  <CoveragePlatformHeader
                    book={OPTIC_BOOK}
                    label={coveragePlatformLabel(OPTIC_BOOK)}
                    league={league}
                    sport={fixture.sport ?? ""}
                    leagueDetail={leagueDetail}
                    normalCase
                  />
                </div>
              </th>
              {bookPlatforms.map((book) => (
                <th key={book} className="px-3 py-2 normal-case">
                  <CoveragePlatformHeader
                    book={book}
                    label={coveragePlatformLabel(book)}
                    league={league}
                    sport={fixture.sport ?? ""}
                    leagueDetail={leagueDetail}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {markets.length === 0 ? (
              <tr className="border-t border-slate-100 dark:border-slate-800">
                <td colSpan={colSpan} className="px-3 py-4 text-xs text-slate-500">
                  No market types on the tip for this league. Platform headers still reflect league
                  wiring — open Editor to add market rules.
                </td>
              </tr>
            ) : null}
            {markets.map((market) => {
                const fullSection = sectionsByCanonical.get(market);
                const stampRows = filteredByCanonical.get(market)?.rows ?? [];
                const totalStampCount = fullSection?.rows.length ?? 0;
                const open = openCanonical === market;
                return (
                  <MarketRuleRows
                    key={market}
                    market={market}
                    bookPlatforms={bookPlatforms}
                    colSpan={colSpan}
                    open={open}
                    stampRows={stampRows}
                    totalStampCount={totalStampCount}
                    bookCounts={fullSection?.bookCounts ?? {}}
                    league={league}
                    rules={rules}
                    toggles={toggles}
                    stampBook={stampBook}
                    stampQuery={stampQuery}
                    onToggle={() => toggleCanonical(market)}
                    onInspectStamps={inspectStamps}
                    onStampBook={setStampBook}
                    onStampQuery={setStampQuery}
                    onSetCell={setCell}
                  />
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MarketRuleRows({
  market,
  bookPlatforms,
  colSpan,
  open,
  stampRows,
  totalStampCount,
  bookCounts,
  league,
  rules,
  toggles,
  stampBook,
  stampQuery,
  onToggle,
  onInspectStamps,
  onStampBook,
  onStampQuery,
  onSetCell,
}: {
  market: string;
  bookPlatforms: string[];
  colSpan: number;
  open: boolean;
  stampRows: CoverageStampRow[];
  totalStampCount: number;
  bookCounts: Record<string, number>;
  league: string;
  rules: MarketRuleRow[];
  toggles: Record<CoverageCellKey, boolean>;
  stampBook: string;
  stampQuery: string;
  onToggle: () => void;
  onInspectStamps: (focus: StampFocus) => void;
  onStampBook: (book: string) => void;
  onStampQuery: (query: string) => void;
  onSetCell: (key: CoverageCellKey, next: boolean) => void;
}) {
  return (
    <>
      <tr
        className={`border-t border-slate-100 dark:border-slate-800 ${
          open ? "bg-slate-50/80 dark:bg-slate-800/40" : ""
        }`}
      >
        <td className="px-3 py-2 align-middle">
          <div className="flex gap-1.5">
            <button
              type="button"
              className="shrink-0 self-center text-slate-400"
              onClick={onToggle}
              aria-expanded={open}
              aria-label={`${open ? "Collapse" : "Expand"} stamps for ${market}`}
            >
              {open ? "▾" : "▸"}
            </button>
            <div className="flex min-w-0 flex-col gap-1">
              <button
                type="button"
                className="text-left font-mono"
                onClick={onToggle}
                aria-expanded={open}
              >
                <span>{market}</span>
                {totalStampCount > 0 ? (
                  <span className="text-[10px] font-sans text-slate-500"> ({totalStampCount})</span>
                ) : null}
              </button>
              <MarketRuleBookCell
                book={OPTIC_BOOK}
                market={market}
                league={league}
                rules={rules}
                toggles={toggles}
                showStampLink={false}
                onSetCell={onSetCell}
              />
            </div>
          </div>
        </td>
        {bookPlatforms.map((book) => (
          <td key={book} className="px-3 py-2 align-middle">
            <MarketRuleBookCell
              book={book}
              market={market}
              league={league}
              rules={rules}
              toggles={toggles}
              cellStampCount={bookCounts[book] ?? 0}
              stampBook={stampBook}
              rowOpen={open}
              showStampLink
              onInspectStamps={onInspectStamps}
              onSetCell={onSetCell}
            />
          </td>
        ))}
      </tr>
      {open ? (
        <tr className="border-t border-slate-100 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-900/40">
          <td colSpan={colSpan} className="px-3 py-3">
            <StampRowsPanel
              market={market}
              rows={stampRows}
              totalCount={totalStampCount}
              books={Object.keys(bookCounts).filter((book) => bookPlatforms.includes(book)).sort()}
              stampBook={stampBook}
              stampQuery={stampQuery}
              onStampBook={onStampBook}
              onStampQuery={onStampQuery}
            />
          </td>
        </tr>
      ) : null}
    </>
  );
}

type MarketRuleBookCellProps = {
  book: string;
  market: string;
  league: string;
  rules: MarketRuleRow[];
  toggles: Record<CoverageCellKey, boolean>;
  onSetCell: (key: CoverageCellKey, next: boolean) => void;
} & (
  | { showStampLink: false }
  | {
      showStampLink: true;
      cellStampCount: number;
      stampBook: string;
      rowOpen: boolean;
      onInspectStamps: (focus: StampFocus) => void;
    }
);

function MarketRuleBookCell(props: MarketRuleBookCellProps) {
  const { book, market, league, rules, toggles, showStampLink, onSetCell } = props;
  const key = coverageCellKey(book, market);
  const hasRule = cellHasRule(rules, book, market);
  const on = Boolean(toggles[key]);
  const source = cellSourceLabel(rules, book, market);
  const stampLinkOpen =
    showStampLink &&
    props.rowOpen &&
    props.stampBook === book &&
    props.cellStampCount > 0;

  return (
    <div className="flex flex-col items-start gap-0.5" onClick={(e) => e.stopPropagation()}>
      {hasRule ? (
        <>
          <BookChipToggle
            book={book}
            text={source}
            enabled={on}
            label={`${book} ${source || market}`}
            title={on ? "Click to ignore" : "Click to map"}
            onToggle={(next) => onSetCell(key, next)}
          />
          {showStampLink && props.cellStampCount > 0 ? (
            <button
              type="button"
              className="text-[10px] text-brand-700 underline dark:text-brand-300"
              title={stampLinkOpen ? "Collapse stamps for this book" : "Expand and filter stamps to this book"}
              aria-expanded={stampLinkOpen}
              onClick={() =>
                props.onInspectStamps({ canonical: market, sportsbook: book })
              }
            >
              {props.cellStampCount} stamp{props.cellStampCount === 1 ? "" : "s"}
            </button>
          ) : null}
        </>
      ) : league ? (
        <Link
          to="/entry"
          state={missingMarketEntryState({ league, sportsbook: book, canonical: market })}
          title="Not on this market. Add a source key in Editor."
          className={`${BOOK_CHIP_BASE} ${bookChipClass({ present: false, enabled: false })}`}
        >
          Add
        </Link>
      ) : (
        <span className={`${BOOK_CHIP_BASE} ${bookChipClass({ present: false, enabled: false })}`}>
          —
        </span>
      )}
    </div>
  );
}

function StampRowsPanel({
  market,
  rows,
  totalCount,
  books,
  stampBook,
  stampQuery,
  onStampBook,
  onStampQuery,
}: {
  market: string;
  rows: CoverageStampRow[];
  totalCount: number;
  books: string[];
  stampBook: string;
  stampQuery: string;
  onStampBook: (book: string) => void;
  onStampQuery: (query: string) => void;
}) {
  if (totalCount === 0) {
    return (
      <p className="text-xs text-slate-500">
        No published stamps for <span className="font-mono">{market}</span> yet.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1">
          <label className="label" htmlFor={`coverage-stamps-${market}`}>
            Search stamps
          </label>
          <input
            id={`coverage-stamps-${market}`}
            className="input w-full"
            placeholder="Book, entity, yes/no, source id…"
            value={stampQuery}
            onChange={(event) => onStampQuery(event.target.value)}
          />
        </div>
        {books.length > 1 ? (
          <div className="flex flex-wrap gap-1">
            <BookFilterPill label="All" active={!stampBook} onClick={() => onStampBook("")} />
            {books.map((book) => (
              <BookFilterPill
                key={book}
                label={sportsbookLabel(book)}
                active={stampBook === book}
                onClick={() => onStampBook(stampBook === book ? "" : book)}
              />
            ))}
          </div>
        ) : null}
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-slate-500">No stamps match the current filter.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-slate-100 text-[10px] uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2">Book</th>
                <th className="px-3 py-2">Optic market_id</th>
                <th className="px-3 py-2">Entity / selection</th>
                <th className="px-3 py-2">Line</th>
                <th className="px-3 py-2">Side</th>
                <th className="px-3 py-2" title="Yes or no on the sportsbook contract">
                  Yes / no
                </th>
                <th className="px-3 py-2">Source id</th>
                <th className="px-3 py-2">Last updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr
                  key={`${row.sportsbook}-${row.entity}-${row.contract_side}-${row.source_id}-${index}`}
                  className="border-t border-slate-100 dark:border-slate-800"
                >
                  <td className="px-3 py-2">{row.sportsbook_label || row.sportsbook}</td>
                  <td className="px-3 py-2 font-mono">{row.market_id || "—"}</td>
                  <td className="px-3 py-2">{row.entity || "—"}</td>
                  <td className="px-3 py-2 font-mono">{row.line || "—"}</td>
                  <td className="px-3 py-2 font-mono">{row.side || "—"}</td>
                  <td className="px-3 py-2 font-mono">{row.contract_side || "—"}</td>
                  <td className="px-3 py-2 font-mono">{row.source_id || "—"}</td>
                  <td className="px-3 py-2 text-slate-500">{formatStampUpdated(row.last_updated)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CoveragePlatformHeader({
  book,
  label,
  league,
  sport,
  leagueDetail,
  normalCase = false,
}: {
  book: string;
  label: string;
  league: string;
  sport: string;
  leagueDetail: CoverageLeagueDetail | null;
  normalCase?: boolean;
}) {
  const caseClass = normalCase ? "normal-case" : "";
  const enabled = leagueDetail ? platformLeagueEnabled(leagueDetail, book) : false;
  const tone = enabled
    ? "text-brand-700 dark:text-brand-300"
    : "text-slate-400 dark:text-slate-500";
  const title = enabled
    ? "Enabled for this league — open Editor"
    : "Not enabled for this league — open Editor";

  if (!league) {
    return <span className={`${tone} ${caseClass}`}>{label}</span>;
  }

  const linkState = leagueDetail
    ? leaguePlatformEntryState(league, leagueDetail, book)
    : coverageLeagueHeaderState(league, book, sport);

  return (
    <Link
      to="/entry"
      state={linkState}
      className={`underline decoration-dotted underline-offset-2 hover:decoration-solid ${tone} ${caseClass}`}
      title={title}
    >
      {label}
    </Link>
  );
}

function BookFilterPill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`rounded px-2 py-1 text-[11px] ${
        active
          ? "bg-brand-100 font-medium text-brand-900 dark:bg-brand-950 dark:text-brand-100"
          : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
      }`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
