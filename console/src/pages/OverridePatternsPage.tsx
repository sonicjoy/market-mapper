import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { LiveAckCheckbox } from "../components/LiveAckCheckbox";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import {
  canPropose,
  readOverridePatternsQuery,
  shapeLabel,
  verdictFor,
  warningFor,
  writeOverridePatternsQuery,
  type OverridePatternsQuery,
  type VerdictTone,
} from "../lib/overridePatterns";
import {
  listOverridePatterns,
  stageOverridePattern,
  type OverridePattern,
  type OverridePatternStageResult,
} from "../overridePatternsApi";

const TONE: Record<VerdictTone, string> = {
  go: "text-emerald-700 dark:text-emerald-300",
  info: "text-slate-600 dark:text-slate-300",
  warn: "text-amber-700 dark:text-amber-300",
  stop: "text-red-700 dark:text-red-300",
};

const KINDS = [
  { value: "", label: "All" },
  { value: "market_rule", label: "Market rules" },
  { value: "alias", label: "Aliases" },
] as const;

function StageOutcome({ result }: { result: OverridePatternStageResult }) {
  const ref = result.review?.ref;
  if (result.ok && ref) {
    return (
      <span className="text-emerald-700 dark:text-emerald-300">
        On Proposed:{" "}
        <Link className="underline" to={`/review/${ref}`}>
          {ref}
        </Link>
      </span>
    );
  }
  const why = result.blockers?.[0] ?? result.detail ?? result.error ?? "not staged";
  return <span className="text-red-700 dark:text-red-300">{why}</span>;
}

function PatternWarningRow({ row }: { row: OverridePattern }) {
  const warning = warningFor(row);
  if (!warning) return null;
  return (
    <tr className="border-b border-slate-100 dark:border-slate-800">
      <td className="px-3 pb-3" colSpan={7}>
        <div className="notice-red text-xs" role="alert">
          <p className="font-semibold">{warning.title}</p>
          <p className="mt-1">{warning.why}</p>
          <p className="mt-1">
            <span className="font-semibold">What to do: </span>
            {warning.todo}
          </p>
          {row.sample_keys.length ? (
            <p className="mt-1 font-mono text-[11px]">Sample overrides: {row.sample_keys.slice(0, 3).join(" · ")}</p>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function PatternRow(props: {
  row: OverridePattern;
  ack: boolean;
  busy: boolean;
  result?: OverridePatternStageResult;
  onPropose: (row: OverridePattern) => void;
}) {
  const { row, ack, busy, result } = props;
  const verdict = verdictFor(row.draft.status);
  return (
    <tr className="border-b border-slate-100 align-top dark:border-slate-800">
      <td className="px-3 py-2">{row.kind === "market_rule" ? "Market rule" : "Alias"}</td>
      <td className="px-3 py-2">
        <div className="font-mono text-[11px]">{shapeLabel(row)}</div>
        <div className="text-slate-500">
          {row.sportsbook} · {row.league}
        </div>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{row.games}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {row.overrides}
        <span className="text-slate-500"> ({row.active} active)</span>
      </td>
      <td className="px-3 py-2">{row.sources.join(", ")}</td>
      <td className={`px-3 py-2 ${TONE[verdict.tone]}`}>
        {verdict.text}
        {row.draft.detail ? <div className="font-mono text-[11px] text-slate-500">{row.draft.detail}</div> : null}
      </td>
      <td className="px-3 py-2">
        {row.proposed ? (
          <span className="text-slate-500">On Proposed</span>
        ) : (
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={!canPropose(row) || !ack || busy}
            title={!ack && canPropose(row) ? "Tick the acknowledgement above first" : undefined}
            onClick={() => props.onPropose(row)}
          >
            {busy ? "Proposing..." : "Propose rule"}
          </button>
        )}
        {result ? (
          <div className="mt-1 text-[11px]">
            <StageOutcome result={result} />
          </div>
        ) : null}
      </td>
    </tr>
  );
}

export function OverridePatternsPage() {
  const [params, setParams] = useSearchParams();
  const query = readOverridePatternsQuery(params);
  const [ack, setAck] = useState(false);
  const [results, setResults] = useState<Record<string, OverridePatternStageResult>>({});
  const forceRefresh = useRef(false);
  const client = useQueryClient();

  const patterns = useQuery({
    queryKey: ["override-patterns", query.kind, query.minGames, query.includeInactive],
    queryFn: () => {
      const refresh = forceRefresh.current;
      forceRefresh.current = false;
      return listOverridePatterns({ ...query, kind: query.kind || undefined, refresh });
    },
    staleTime: 60 * 1000,
  });

  const stage = useMutation({
    mutationFn: (row: OverridePattern) => stageOverridePattern(row.cluster_id, ack),
    onSuccess: (result, row) => {
      setResults((prev) => ({ ...prev, [row.cluster_id]: result }));
      if (result.ok) void client.invalidateQueries({ queryKey: ["override-patterns"] });
    },
    onError: (err: Error, row) => {
      setResults((prev) => ({ ...prev, [row.cluster_id]: { ok: false, error: err.message } }));
    },
  });

  function patch(next: Partial<OverridePatternsQuery>) {
    setParams(writeOverridePatternsQuery(params, next));
  }

  const rows = patterns.data?.clusters ?? [];
  const unparsed = Object.entries(patterns.data?.unparsed ?? {});
  const warned = rows.filter((row) => warningFor(row) && row.active > 0);
  return (
    <div>
      <PageHeader
        title="Override patterns"
        description="Overrides repeated across fixtures, grouped into the market rule or alias that would replace them. Proposing drafts through the same kernel as the Cart and lands on Proposed for human Approve."
      >
        <RefreshButton
          busy={patterns.isFetching}
          onClick={() => {
            forceRefresh.current = true;
            return patterns.refetch();
          }}
        />
      </PageHeader>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label className="label" htmlFor="op-kind">
            Kind
          </label>
          <select
            id="op-kind"
            className="input w-40"
            value={query.kind}
            onChange={(e) => patch({ kind: e.target.value as OverridePatternsQuery["kind"] })}
          >
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="op-min">
            Min fixtures
          </label>
          <input
            id="op-min"
            type="number"
            min={1}
            className="input w-24"
            value={query.minGames}
            onChange={(e) => patch({ minGames: Math.max(1, Number(e.target.value) || 1) })}
          />
        </div>
        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-brand-600"
            checked={query.includeInactive}
            onChange={(e) => patch({ includeInactive: e.target.checked })}
          />
          Include deactivated overrides
        </label>
      </div>
      <div className="mb-3">
        <LiveAckCheckbox checked={ack} onChange={setAck} />
      </div>
      {patterns.data?.error ? <p className="notice-red mb-2 text-sm">{patterns.data.error}</p> : null}
      {patterns.isError ? <p className="notice-red mb-2 text-sm">{patterns.error.message}</p> : null}
      {unparsed.length ? (
        <p className="mb-2 text-xs text-slate-500">
          Not clustered: {unparsed.map(([k, n]) => `${k} ${n.toLocaleString()}`).join(" · ")}
        </p>
      ) : null}
      {warned.length ? (
        <p className="notice-red mb-2 text-sm" role="alert">
          {warned.length} repeated pattern(s) cannot become a rule and still carry{" "}
          {warned.reduce((n, r) => n + r.active, 0).toLocaleString()} active override(s). Each is explained below; no
          rule is proposed for them automatically.
        </p>
      ) : null}
      {patterns.isLoading ? <p className="text-sm text-slate-500">Loading overrides...</p> : null}
      {patterns.data && !rows.length ? (
        <p className="text-sm text-slate-500">No override repeats across {query.minGames}+ fixtures.</p>
      ) : null}
      {rows.length ? (
        <div className="card overflow-x-auto p-0">
          <table className="w-full min-w-[56rem] text-left text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
              <tr>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2">Pattern</th>
                <th className="px-3 py-2 text-right">Fixtures</th>
                <th className="px-3 py-2 text-right">Overrides</th>
                <th className="px-3 py-2">Written by</th>
                <th className="px-3 py-2">Kernel verdict</th>
                <th className="px-3 py-2 w-40" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.cluster_id}>
                  <PatternRow
                    row={row}
                    ack={ack}
                    busy={stage.isPending && stage.variables?.cluster_id === row.cluster_id}
                    result={results[row.cluster_id]}
                    onPropose={(r) => stage.mutate(r)}
                  />
                  <PatternWarningRow row={row} />
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
