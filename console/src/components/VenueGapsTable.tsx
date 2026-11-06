import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { formatFixtureStart } from "../lib/coverageList";
import {
  arrangeMarkets,
  arrangeSelections,
  coverageOf,
  mappedPct,
  nodeId,
  type Coverage,
  type VenueGapNode,
} from "../lib/venueGapsTree";
import {
  FIXTURE_STALE_MS,
  fixtureQueryKey,
  getVenueGapFixture,
  type VenueGapLeague,
  type VenueGapTipStatus,
} from "../venueGapsApi";

type Counts = { total: number; mapped: number; unmapped: number; demand: number };

type TableProps = {
  platform: string;
  leagues: VenueGapLeague[];
  unmappedOnly: boolean;
  /** Picked market names; the fixture drill-down hides the rest. */
  markets: string[];
  selectedId: string | null;
  open: ReadonlySet<string>;
  onSelect: (node: VenueGapNode) => void;
  onToggle: (id: string) => void;
};

const INDENT = ["pl-3", "pl-9", "pl-[3.75rem]", "pl-[5.25rem]"] as const;

const COVERAGE_CHIP: Record<Coverage, { label: string; className: string }> = {
  mapped: {
    label: "Mapped",
    className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  },
  partial: {
    label: "Partial",
    className: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  },
  unmapped: {
    label: "Unmapped",
    className: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  },
};

const TIP_CHIP: Record<Exclude<VenueGapTipStatus, "in_tip">, string> = {
  disabled: "crypto.com off",
  not_in_tip: "Not in tip",
};

const BAR: Record<Coverage, string> = {
  mapped: "bg-brand-600",
  partial: "bg-amber-500",
  unmapped: "bg-red-600",
};

function Chip({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${className}`}>{children}</span>;
}

function StatusCell({ counts, tip, noLeague }: { counts: Counts; tip?: VenueGapTipStatus; noLeague?: boolean }) {
  if (tip && tip !== "in_tip") {
    return (
      <Chip className="bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100">
        {noLeague ? "No league" : TIP_CHIP[tip]}
      </Chip>
    );
  }
  const chip = COVERAGE_CHIP[coverageOf(counts)];
  return <Chip className={chip.className}>{chip.label}</Chip>;
}

function CountCells({ counts, tip, noLeague }: { counts: Counts; tip?: VenueGapTipStatus; noLeague?: boolean }) {
  const pct = mappedPct(counts);
  return (
    <>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <div
            className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`${pct}% mapped`}
          >
            <div className={`h-full ${BAR[coverageOf(counts)]}`} style={{ width: `${pct}%` }} />
          </div>
          <span className="whitespace-nowrap tabular-nums text-slate-600 dark:text-slate-300">
            {counts.mapped.toLocaleString()} / {counts.total.toLocaleString()}
          </span>
        </div>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        <span className={counts.unmapped ? "font-semibold text-red-700 dark:text-red-300" : "text-slate-400"}>
          {counts.unmapped.toLocaleString()}
        </span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{counts.demand.toLocaleString()}</td>
      <td className="px-3 py-2">
        <StatusCell counts={counts} tip={tip} noLeague={noLeague} />
      </td>
    </>
  );
}

function Caret({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M7 5l6 5-6 5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type NodeRowProps = {
  node: VenueGapNode;
  depth: 0 | 1 | 2 | 3;
  kind: string;
  title: string;
  subtitle?: string;
  /** Symbols and venue codes read better in mono; dates and market groups do not. */
  monoSubtitle?: boolean;
  counts: Counts;
  tip?: VenueGapTipStatus;
  noLeague?: boolean;
  expandable: boolean;
  isOpen: boolean;
  selected: boolean;
  onSelect: (node: VenueGapNode) => void;
  onToggle: (id: string) => void;
};

function NodeRow(props: NodeRowProps) {
  const { node, depth, kind, title, subtitle, monoSubtitle, counts, tip, expandable, isOpen, selected } = props;
  const id = nodeId(node);
  const rowClass = selected
    ? "bg-brand-50 dark:bg-brand-950/40"
    : "hover:bg-slate-50 dark:hover:bg-slate-800/40";
  return (
    <tr className={`border-b border-slate-100 dark:border-slate-800 ${rowClass}`} aria-selected={selected}>
      <td className={`py-1.5 pr-3 ${INDENT[depth]}`}>
        <div className="flex min-w-0 items-center gap-1.5">
          {expandable ? (
            <button
              type="button"
              className="rounded p-1 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
              aria-expanded={isOpen}
              aria-label={`${isOpen ? "Collapse" : "Expand"} ${title}`}
              onClick={() => props.onToggle(id)}
            >
              <Caret open={isOpen} />
            </button>
          ) : (
            <span className="w-[1.375rem] shrink-0" />
          )}
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{kind}</span>
          <button
            type="button"
            className="min-w-0 truncate text-left font-medium text-slate-900 hover:underline dark:text-slate-100"
            title={subtitle ? `${title} — ${subtitle}` : title}
            onClick={() => props.onSelect(node)}
          >
            {title}
          </button>
          {subtitle ? (
            <span className={`truncate text-[11px] text-slate-500 ${monoSubtitle ? "font-mono" : ""}`}>{subtitle}</span>
          ) : null}
        </div>
      </td>
      <CountCells counts={counts} tip={tip} noLeague={props.noLeague} />
    </tr>
  );
}

function selectionCounts(mapped: boolean, demand: number): Counts {
  return { total: 1, mapped: mapped ? 1 : 0, unmapped: mapped ? 0 : 1, demand };
}

function FixtureChildren(props: {
  platform: string;
  meta: string;
  fixtureKey: string;
  unmappedOnly: boolean;
  markets: string[];
  selectedId: string | null;
  open: ReadonlySet<string>;
  onSelect: (node: VenueGapNode) => void;
  onToggle: (id: string) => void;
}) {
  const { platform, meta, fixtureKey, unmappedOnly, markets, selectedId, open } = props;
  const detail = useQuery({
    queryKey: fixtureQueryKey(platform, fixtureKey),
    queryFn: () => getVenueGapFixture(platform, fixtureKey),
    staleTime: FIXTURE_STALE_MS,
  });
  if (detail.isLoading || detail.isError || detail.data?.error) {
    const text = detail.isLoading
      ? "Loading markets…"
      : `Could not load markets: ${detail.data?.error ?? detail.error?.message ?? "unknown error"}`;
    return (
      <tr>
        <td colSpan={5} className={`py-2 text-slate-500 ${INDENT[2]}`}>
          {text}
        </td>
      </tr>
    );
  }
  return (
    <>
      {arrangeMarkets(detail.data?.markets ?? [], unmappedOnly, markets).map((market) => {
        const marketNode: VenueGapNode = { kind: "market", meta, fixtureKey, marketId: market.market_id };
        const marketOpen = open.has(nodeId(marketNode));
        return [
          <NodeRow
            key={nodeId(marketNode)}
            node={marketNode}
            depth={2}
            kind="Market"
            title={market.label}
            subtitle={market.market_group}
            counts={market}
            expandable
            isOpen={marketOpen}
            selected={selectedId === nodeId(marketNode)}
            onSelect={props.onSelect}
            onToggle={props.onToggle}
          />,
          ...(marketOpen
            ? arrangeSelections(market.selections, unmappedOnly).map((sel) => {
                const selNode: VenueGapNode = { ...marketNode, kind: "selection", key: sel.key };
                return (
                  <NodeRow
                    key={nodeId(selNode)}
                    node={selNode}
                    depth={3}
                    kind="Sel"
                    title={sel.outcome}
                    subtitle={sel.key}
                    monoSubtitle
                    counts={selectionCounts(sel.mapped, sel.demand)}
                    expandable={false}
                    isOpen={false}
                    selected={selectedId === nodeId(selNode)}
                    onSelect={props.onSelect}
                    onToggle={props.onToggle}
                  />
                );
              })
            : []),
        ];
      })}
    </>
  );
}

export function VenueGapsTable(props: TableProps) {
  const { platform, leagues, unmappedOnly, markets, selectedId, open } = props;
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full min-w-[46rem] table-fixed text-left text-xs">
        <colgroup>
          <col />
          <col className="w-52" />
          <col className="w-24" />
          <col className="w-28" />
          <col className="w-28" />
        </colgroup>
        <thead className="border-b border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
          <tr>
            <th className="px-3 py-2 font-medium">League / fixture / market / selection</th>
            <th className="whitespace-nowrap px-3 py-2 font-medium">Mapped</th>
            <th className="whitespace-nowrap px-3 py-2 text-right font-medium">Unmapped</th>
            <th
              className="whitespace-nowrap px-3 py-2 text-right font-medium"
              title="RFQ legs that failed mapping in the last 48h"
            >
              Failed RFQs 48h
            </th>
            <th className="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        {leagues.map((league) => {
          const leagueNode: VenueGapNode = { kind: "league", meta: league.meta_league };
          const leagueOpen = open.has(nodeId(leagueNode));
          return (
            <tbody key={league.meta_league}>
              <NodeRow
                node={leagueNode}
                depth={0}
                kind="League"
                title={league.tip.league_label ?? league.meta_league}
                subtitle={league.tip.league ? league.meta_league : undefined}
                monoSubtitle
                counts={league}
                tip={league.tip.status}
                noLeague={league.tip.status !== "in_tip" && !league.tip.fix}
                expandable
                isOpen={leagueOpen}
                selected={selectedId === nodeId(leagueNode)}
                onSelect={props.onSelect}
                onToggle={props.onToggle}
              />
              {leagueOpen
                ? league.fixtures.map((fixture) => {
                    const fxNode: VenueGapNode = {
                      kind: "fixture",
                      meta: league.meta_league,
                      fixtureKey: fixture.fixture_key,
                    };
                    const fxOpen = open.has(nodeId(fxNode));
                    return [
                      <NodeRow
                        key={nodeId(fxNode)}
                        node={fxNode}
                        depth={1}
                        kind="Fixture"
                        title={fixture.name}
                        subtitle={formatFixtureStart(fixture.start_date)}
                        counts={fixture}
                        expandable
                        isOpen={fxOpen}
                        selected={selectedId === nodeId(fxNode)}
                        onSelect={props.onSelect}
                        onToggle={props.onToggle}
                      />,
                      fxOpen ? (
                        <FixtureChildren
                          key={`${nodeId(fxNode)}:children`}
                          platform={platform}
                          meta={league.meta_league}
                          fixtureKey={fixture.fixture_key}
                          unmappedOnly={unmappedOnly}
                          markets={markets}
                          selectedId={selectedId}
                          open={open}
                          onSelect={props.onSelect}
                          onToggle={props.onToggle}
                        />
                      ) : null,
                    ];
                  })
                : null}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}
