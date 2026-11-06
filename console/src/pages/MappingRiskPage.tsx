import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useRef } from "react";

import { MappingRiskFlagCell } from "../components/MappingRiskFlagCell";
import { PageHeader } from "../components/PageHeader";
import { CacheNote } from "../components/CacheNote";
import { RefreshButton } from "../components/RefreshButton";
import { RulesPager } from "../components/RulesPager";
import { TableFetchOverlay } from "../components/TableFetchOverlay";
import { formatFixtureStart } from "../lib/coverageList";
import {
  RISK_PLATFORMS,
  RISK_TIERS,
  SIGNAL_LABELS,
  impliedPair,
  readMappingRiskQuery,
  writeMappingRiskQuery,
  type MappingRiskQueryState,
} from "../lib/mappingRiskQuery";
import { listMappingRisk, type MappingRiskResponse, type MappingRiskRow, type RiskTier } from "../mappingRiskApi";
import { usePageFilters } from "../usePageFilters";

const TIER_CHIP: Record<RiskTier, string> = {
  high: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  medium: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  low: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
};

function TierChip({ tier }: { tier: RiskTier | null }) {
  if (!tier) return <span className="text-slate-400">—</span>;
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${TIER_CHIP[tier]}`}>{tier}</span>;
}

function Tiles({ data }: { data: MappingRiskResponse }) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
      {RISK_TIERS.map((tier) => (
        <div key={tier} className="card px-3 py-2">
          <p className="text-xs capitalize text-slate-600 dark:text-slate-300">{tier} risk</p>
          <p className="text-lg font-semibold tabular-nums">{(data.facets.tiers[tier] ?? 0).toLocaleString()}</p>
        </div>
      ))}
      <div className="card px-3 py-2">
        <p className="text-xs text-slate-600 dark:text-slate-300">Open flags on this page</p>
        <p className="text-lg font-semibold tabular-nums">
          {data.rows.filter((r) => r.flag?.status === "open").length}
        </p>
      </div>
    </div>
  );
}

function CoverageGaps({ data, platform }: { data: MappingRiskResponse; platform: string }) {
  const rows = data.coverage.filter((c) => c.missing.length && (!platform || c.platform === platform));
  if (!rows.length) return null;
  return (
    <details className="mb-3 text-xs text-slate-600 dark:text-slate-300">
      <summary className="cursor-pointer">Signals that cannot fire (no evidence source) — an empty column is not "clean"</summary>
      <ul className="mt-1 space-y-0.5">
        {rows.map((c) => (
          <li key={c.platform}>
            <span className="font-medium">{c.platform}</span>: {c.missing.join("; ")}
          </li>
        ))}
      </ul>
    </details>
  );
}

function RiskRow({ row }: { row: MappingRiskRow }) {
  const line = [row.selection_line, row.points ? String(row.points) : ""].filter(Boolean).join(" ");
  const price = impliedPair(row.venue_price, row.fair_price);
  return (
    <tr className="border-b border-slate-100 align-top dark:border-slate-800">
      <td className="px-3 py-2">
        <TierChip tier={row.tier} />
      </td>
      <td className="px-3 py-2">
        {row.book ?? row.sb}
        {row.is_rfq_winner ? <p className="text-[10px] font-medium text-brand-700 dark:text-brand-300">served</p> : null}
      </td>
      <td className="whitespace-nowrap px-3 py-2">{formatFixtureStart(row.start_date)}</td>
      <td className="px-3 py-2">
        <p className="font-medium">{row.selection || "—"} {line}</p>
        <p className="text-[11px] text-slate-500">
          {row.market_id} · {row.league ?? "?"} · <span className="font-mono">{row.game_id}</span>
        </p>
        {row.exchange_text ? <p className="text-[11px] italic text-slate-500">venue: {row.exchange_text}</p> : null}
      </td>
      <td className="max-w-[14rem] break-all px-3 py-2 font-mono text-[10px]">{row.src_key}</td>
      <td className="px-3 py-2 text-[11px]">
        <ul className="space-y-0.5">
          {row.signals.map((s) => (
            <li key={s.code}>
              <TierChip tier={s.tier} /> <span className="font-medium">{SIGNAL_LABELS[s.code] ?? s.code}</span>: {s.text}
            </li>
          ))}
        </ul>
        {price ? <p className="mt-1 text-slate-500">venue vs fair: {price}</p> : null}
        <p className="mt-1 text-slate-400">
          {row.mapping_source}
          {row.rank_class ? ` / ${row.rank_class}` : ""}
        </p>
      </td>
      <td className="w-56 px-3 py-2">
        <MappingRiskFlagCell row={row} />
      </td>
    </tr>
  );
}

type Patch = (next: Partial<MappingRiskQueryState>, opts?: { replace?: boolean }) => void;

function SelectField(props: {
  id: string;
  label: string;
  width: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="label" htmlFor={props.id}>
        {props.label}
      </label>
      <select
        id={props.id}
        className={`input ${props.width}`}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
      >
        {props.options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function WindowField(props: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div>
      <label className="label" htmlFor={props.id}>
        {props.label}
      </label>
      <input
        id={props.id}
        type="datetime-local"
        className="input w-52"
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </div>
  );
}

function reasonOptions(state: MappingRiskQueryState, data?: MappingRiskResponse) {
  const counted = Object.entries(data?.facets.reasons ?? {}).sort((a, b) => b[1] - a[1]);
  const opts = counted.map(([code, n]) => ({ value: code, label: `${SIGNAL_LABELS[code] ?? code} (${n.toLocaleString()})` }));
  // A picked signal the other filters now exclude stays listed so it can be cleared.
  if (state.reason && !counted.some(([code]) => code === state.reason)) {
    opts.unshift({ value: state.reason, label: `${SIGNAL_LABELS[state.reason] ?? state.reason} (0)` });
  }
  return [{ value: "", label: "All" }, ...opts];
}

function Filters({ state, data, patch }: { state: MappingRiskQueryState; data?: MappingRiskResponse; patch: Patch }) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-2">
      <div className="min-w-[12rem] flex-1">
        <label className="label" htmlFor="risk-q">
          Search
        </label>
        <input
          id="risk-q"
          className="input w-full"
          placeholder="Selection, market, league, venue id or game id"
          value={state.q}
          onChange={(e) => patch({ q: e.target.value }, { replace: true })}
        />
      </div>
      <SelectField
        id="risk-platform"
        label="Platform"
        width="w-40"
        value={state.platform}
        options={[...RISK_PLATFORMS]}
        onChange={(platform) => patch({ platform })}
      />
      <SelectField
        id="risk-tier"
        label="Tier"
        width="w-32"
        value={state.tier}
        options={[{ value: "", label: "All" }, ...RISK_TIERS.map((t) => ({ value: t, label: t }))]}
        onChange={(tier) => patch({ tier })}
      />
      <SelectField
        id="risk-reason"
        label="Signal"
        width="w-56"
        value={state.reason}
        options={reasonOptions(state, data)}
        onChange={(reason) => patch({ reason })}
      />
      <WindowField
        id="risk-from"
        label="Kickoff from (UTC)"
        value={state.kickoffFrom}
        onChange={(kickoffFrom) => patch({ kickoffFrom }, { replace: true })}
      />
      <WindowField
        id="risk-to"
        label="Kickoff to (UTC)"
        value={state.kickoffTo}
        onChange={(kickoffTo) => patch({ kickoffTo }, { replace: true })}
      />
      <label className="flex items-center gap-2 pb-1.5 text-sm text-slate-700 dark:text-slate-200">
        <input
          type="checkbox"
          className="h-4 w-4 accent-brand-600"
          checked={state.flagged}
          onChange={(e) => patch({ flagged: e.target.checked })}
        />
        Open flags only
      </label>
    </div>
  );
}

export function MappingRiskPage() {
  const [params, setParams] = usePageFilters("mapping-risk");
  const state = readMappingRiskQuery(params);
  const forceRefresh = useRef(false);
  const risk = useQuery({
    queryKey: ["mapping-risk", state],
    queryFn: () => {
      const refresh = forceRefresh.current;
      forceRefresh.current = false;
      return listMappingRisk({ ...state, limit: state.limit, offset: state.page * state.limit, refresh });
    },
    placeholderData: keepPreviousData,
    staleTime: 60 * 1000,
  });

  const patch: Patch = (next, opts) => {
    setParams(writeMappingRiskQuery(params, { page: 0, ...next }), opts);
  };

  const data = risk.data;
  return (
    <div>
      <PageHeader
        title="Mapping risk"
        description="Live mappings (in-play and the next 48h) scored for being wrong: Optic disagrees, one venue id on several markets, the AI validator, name, price and period checks. Riskiest and served first. Flag one to record it; un-map through Editor, Cart and Proposed."
      >
        <RefreshButton
          busy={risk.isFetching}
          onClick={() => {
            forceRefresh.current = true;
            return risk.refetch();
          }}
        />
      </PageHeader>
      <CacheNote cachedAt={data?.cached_at} scanCost="about 1.8 GB of BigQuery" />
      <Filters state={state} data={data} patch={patch} />
      {data?.error ? <p className="notice-red mb-2 text-sm">{data.error}</p> : null}
      {risk.isError ? <p className="notice-red mb-2 text-sm">{risk.error.message}</p> : null}
      {data ? <Tiles data={data} /> : null}
      {data ? <CoverageGaps data={data} platform={state.platform} /> : null}
      {risk.isLoading ? <p className="text-sm text-slate-500">Scoring live mappings…</p> : null}
      <div className="card relative min-h-[14rem] overflow-x-auto p-0">
        <TableFetchOverlay active={risk.isFetching} label="Scoring…" />
        <table className={`w-full text-left text-xs ${risk.isFetching ? "opacity-60" : ""}`}>
          <thead className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
            <tr>
              <th className="px-3 py-2">Tier</th>
              <th className="px-3 py-2">Platform</th>
              <th className="px-3 py-2">Kickoff</th>
              <th className="px-3 py-2">Mapped to</th>
              <th className="px-3 py-2">Venue id</th>
              <th className="px-3 py-2">Why</th>
              <th className="px-3 py-2">Flag</th>
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((row) => <RiskRow key={row.fingerprint} row={row} />)}
          </tbody>
        </table>
        {data && !data.rows.length && !data.error ? (
          <p className="p-3 text-sm text-slate-500">Nothing scores as risky for these filters.</p>
        ) : null}
        <RulesPager
          count={data?.count ?? 0}
          page={state.page}
          pageSize={state.limit}
          onPage={(page) => patch({ page })}
          onPageSize={(limit) => patch({ limit, page: 0 })}
        />
      </div>
    </div>
  );
}
