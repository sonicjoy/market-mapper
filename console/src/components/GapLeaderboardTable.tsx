import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import { formatFixtureStart } from "../lib/coverageList";
import { fixtureNodeId, leagueNodeId, platformNodeId } from "../lib/gapLeaderboardTree";
import type { GapFixture, GapLeague, GapMarket, GapPlatform } from "../gapLeaderboardApi";

type Counts = { demand: number; unmapped: number; legs: number };

const INDENT = ["pl-3", "pl-9", "pl-[3.75rem]", "pl-[5.25rem]"] as const;

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

function FixLink({ to }: { to: string | null }) {
  if (!to) {
    return (
      <span className="text-[11px] text-slate-400" title="No console page inventories this venue yet">
        -
      </span>
    );
  }
  return (
    <Link className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-300" to={to}>
      Fix
    </Link>
  );
}

type RowProps = {
  id: string;
  depth: 0 | 1 | 2 | 3;
  kind: string;
  title: string;
  subtitle?: string;
  counts: Counts;
  sum?: boolean;
  badge?: string;
  kickoff?: string;
  fix?: string | null;
  open?: boolean;
  onToggle?: (id: string) => void;
};

function Row(props: RowProps) {
  const { id, depth, kind, title, subtitle, counts, open, onToggle } = props;
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40">
      <td className={`py-1.5 pr-3 ${INDENT[depth]}`}>
        <div className="flex min-w-0 items-center gap-1.5">
          {onToggle ? (
            <button
              type="button"
              className="rounded p-1 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
              aria-expanded={Boolean(open)}
              aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
              onClick={() => onToggle(id)}
            >
              <Caret open={Boolean(open)} />
            </button>
          ) : (
            <span className="w-[1.375rem] shrink-0" />
          )}
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{kind}</span>
          <span className="min-w-0 truncate font-medium text-slate-900 dark:text-slate-100" title={title}>
            {title}
          </span>
          {subtitle ? <span className="truncate font-mono text-[11px] text-slate-500">{subtitle}</span> : null}
          {props.badge ? (
            <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              {props.badge}
            </span>
          ) : null}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-slate-600 dark:text-slate-300">{props.kickoff ?? ""}</td>
      <td
        className="px-3 py-1.5 text-right tabular-nums"
        title={props.sum ? "Sum of children: an RFQ with legs in two of them counts twice" : undefined}
      >
        {counts.demand.toLocaleString()}
        {props.sum ? <span className="text-slate-400">*</span> : null}
      </td>
      <td className="px-3 py-1.5 text-right tabular-nums">
        <span className={counts.unmapped ? "font-semibold text-red-700 dark:text-red-300" : "text-slate-400"}>
          {counts.unmapped.toLocaleString()}
        </span>
      </td>
      <td className="px-3 py-1.5">{props.fix !== undefined ? <FixLink to={props.fix} /> : null}</td>
    </tr>
  );
}

function kickoffText(fx: GapFixture): string {
  if (!fx.start_date) return "TBD";
  return fx.kickoff_date_only ? fx.start_date.slice(0, 10) : formatFixtureStart(fx.start_date);
}

function marketRows(platform: string, league: string, fx: GapFixture): ReactElement[] {
  return fx.markets.map((m: GapMarket) => (
    <Row
      key={`${fixtureNodeId(platform, league, fx.fixture_key)}:${m.market}`}
      id={m.market}
      depth={3}
      kind="Market"
      title={m.market}
      counts={m}
      fix={m.fix_link}
    />
  ));
}

function fixtureRows(p: GapPlatform, lg: GapLeague, open: ReadonlySet<string>, onToggle: (id: string) => void) {
  return lg.fixtures.flatMap((fx) => {
    const id = fixtureNodeId(p.id, lg.key, fx.fixture_key);
    const isOpen = open.has(id);
    const row = (
      <Row
        key={id}
        id={id}
        depth={2}
        kind="Fixture"
        title={fx.name}
        subtitle={fx.name === fx.fixture_key ? undefined : fx.fixture_key}
        counts={fx}
        sum={fx.demand_is_sum}
        kickoff={kickoffText(fx)}
        fix={fx.fix_link}
        open={isOpen}
        onToggle={fx.markets.length ? onToggle : undefined}
      />
    );
    return isOpen ? [row, ...marketRows(p.id, lg.key, fx)] : [row];
  });
}

function leagueRows(p: GapPlatform, open: ReadonlySet<string>, onToggle: (id: string) => void) {
  return p.leagues.flatMap((lg) => {
    const id = leagueNodeId(p.id, lg.key);
    const isOpen = open.has(id);
    const row = (
      <Row
        key={id}
        id={id}
        depth={1}
        kind="League"
        title={lg.label}
        subtitle={lg.in_tip && lg.hint && lg.hint !== lg.label ? lg.hint : undefined}
        counts={lg}
        sum
        badge={lg.in_tip ? undefined : "Not in tip"}
        open={isOpen}
        onToggle={onToggle}
      />
    );
    return isOpen ? [row, ...fixtureRows(p, lg, open, onToggle)] : [row];
  });
}

export function GapLeaderboardTable({
  platforms,
  open,
  onToggle,
}: {
  platforms: GapPlatform[];
  open: ReadonlySet<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full min-w-[46rem] table-fixed text-left text-xs">
        <colgroup>
          <col />
          <col className="w-40" />
          <col className="w-28" />
          <col className="w-28" />
          <col className="w-14" />
        </colgroup>
        <thead className="border-b border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
          <tr>
            <th className="px-3 py-2 font-medium">Platform / league / fixture / market</th>
            <th className="px-3 py-2 font-medium">Kickoff (UTC)</th>
            <th className="px-3 py-2 text-right font-medium" title="Distinct RFQs that failed mapping in the window">
              Failed RFQs
            </th>
            <th
              className="px-3 py-2 text-right font-medium"
              title="Catalogue selections with no mapping (crypto.com), else distinct failed legs"
            >
              Unmapped
            </th>
            <th className="px-3 py-2 font-medium" />
          </tr>
        </thead>
        {platforms.map((p) => {
          const id = platformNodeId(p.id);
          const isOpen = open.has(id);
          return (
            <tbody key={p.id}>
              <Row
                id={id}
                depth={0}
                kind="Platform"
                title={p.label}
                counts={p}
                sum={p.demand_is_sum}
                badge={p.leagues_not_in_tip ? `${p.leagues_not_in_tip} leagues not in tip` : undefined}
                open={isOpen}
                onToggle={onToggle}
              />
              {isOpen ? leagueRows(p, open, onToggle) : null}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}
