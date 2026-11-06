import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate } from "react-router-dom";

import {
  getCatalogOverrideJob,
  getMeta,
  lookupCatalog,
  publishCatalogOverride,
} from "../api";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import {
  applyCatalogPrefill,
  buildLookupKey,
  canPublishCatalogOverride,
  catalogLookupChanged,
  catalogRowSummary,
  EMPTY_OVERRIDE_FIELDS,
  formatCatalogRowValue,
  laneKeyHint,
  lookupFailedReason,
  lookupFeedbackClass,
  lookupKeysEqual,
  outsideRankWindowWarning,
  overrideFormDisabledReason,
  unreadOverrideReason,
  prepareCatalogLookup,
  winnerPanelClass,
  winnerPanelTitle,
  winnerPrefillKey,
} from "../lib/catalogLookup";

const SPORTSBOOKS = [
  "Kalshi",
  "Polymarket",
  "Polymarket (USA)",
  "crypto.com",
  "Novig",
  "Underdog",
  "DKEX",
  "Prophet X",
  "SX Bet",
];

const TERMINAL_JOB_STATUSES = new Set(["materialised", "accepted_not_materialised", "failed"]);

type OverrideForm = {
  sportsbook: string;
  gameId: string;
  marketId: string;
  selection: string;
  selectionLine: string;
  points: number;
  selectionPoints: number;
  groupingKey: string;
  sourceMarketId: string;
  sourceSelectionId: string;
  mappingSource: string;
  reason: string;
};

function CatalogRowSummary({ row }: { row: Record<string, unknown> }) {
  const lines = catalogRowSummary(row);
  return (
    <dl className="mt-2 grid gap-1 text-xs">
      {lines.map(({ label, value }) => (
        <div key={label} className="grid grid-cols-[10rem_1fr] gap-2">
          <dt className="font-mono text-slate-500">{label}</dt>
          <dd className="break-all font-mono">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function JobStepsSummary({ steps }: { steps: Record<string, unknown> }) {
  const entries = Object.entries(steps);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-3 grid gap-1 text-xs">
      {entries.map(([step, value]) => (
        <div key={step} className="grid grid-cols-[8rem_1fr] gap-2">
          <dt className="font-mono text-slate-500">{step}</dt>
          <dd className="break-all font-mono">{formatCatalogRowValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CatalogPage() {
  const [form, setForm] = useState<OverrideForm>({
    sportsbook: "Kalshi",
    gameId: "",
    marketId: "",
    selection: "",
    selectionLine: "",
    points: 0,
    selectionPoints: 0,
    groupingKey: "default",
    sourceMarketId: "",
    sourceSelectionId: "",
    mappingSource: "",
    reason: "",
  });
  const [lookupKey, setLookupKey] = useState<{
    sportsbook: string;
    source_market_id: string;
    source_selection_id: string;
  } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const lastPrefillKeyRef = useRef<string | null>(null);

  const lookup = useQuery({
    queryKey: ["catalog", lookupKey],
    queryFn: () =>
      lookupCatalog({
        sportsbook: lookupKey!.sportsbook,
        source_market_id: lookupKey!.source_market_id,
        source_selection_id: lookupKey!.source_selection_id,
      }),
    enabled: lookupKey != null,
    refetchOnWindowFocus: false,
  });

  const job = useQuery({
    queryKey: ["catalog-job", jobId],
    queryFn: () => getCatalogOverrideJob(jobId!),
    enabled: jobId != null,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || TERMINAL_JOB_STATUSES.has(status)) return false;
      return 2000;
    },
  });
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: getMeta });

  const override = useMutation({
    mutationFn: publishCatalogOverride,
    onSuccess: (result) => {
      setOverrideError(null);
      setJobId(result.job_id);
      if (lookupKey) lookup.refetch();
    },
    onError: (err: Error) => {
      setOverrideError(err.message);
    },
  });

  useEffect(() => {
    if (!lookup.isSuccess || !lookup.data || lookup.isFetching || !lookupKey) return;
    if (!lookupKeysEqual(lookupKey, buildLookupKey(form))) return;
    const prefillKey = winnerPrefillKey(lookupKey, lookup.data.winner);
    if (lastPrefillKeyRef.current === prefillKey) return;

    setForm((prev) => applyCatalogPrefill(prev, lookup.data));
    lastPrefillKeyRef.current = prefillKey;
  }, [
    lookup.isSuccess,
    lookup.data,
    lookup.isFetching,
    lookupKey,
    form.sportsbook,
    form.sourceMarketId,
    form.sourceSelectionId,
  ]);

  const winner = lookup.data?.winner ?? null;
  const candidates = lookup.data?.candidates ?? [];
  const lookupRequested = lookupKey != null;
  const lookupBusy = lookupRequested && (lookup.isLoading || lookup.isFetching);
  const lookupKeysMatch = lookupKey !== null && lookupKeysEqual(lookupKey, buildLookupKey(form));
  const lookupCurrent = lookup.isSuccess && lookupKeysMatch;
  const canLookup = useMemo(
    () => form.sportsbook.trim() && form.sourceMarketId.trim(),
    [form.sportsbook, form.sourceMarketId],
  );
  const submitGate = {
    form,
    lookupKey,
    lookupSuccess: lookupCurrent,
  };
  const canPublishOverride = canPublishCatalogOverride(submitGate);
  const unreadReason = unreadOverrideReason(meta?.override_unread_sportsbooks, form.sportsbook);
  const formIssuesReason = lookupCurrent ? overrideFormDisabledReason(form) : null;
  const lookupErrorReason = lookupFailedReason({
    lookupKey,
    form,
    isError: lookup.isError,
    errorMessage: lookup.isError ? (lookup.error as Error).message : undefined,
  });
  const rankWindowWarning = lookupCurrent
    ? outsideRankWindowWarning({
        candidateCount: lookup.data?.candidate_count ?? 0,
        inRankWindow: lookup.data?.in_rank_window,
      })
    : null;

  function clearOverrideJobState() {
    setJobId(null);
    setOverrideError(null);
  }

  function patchForm(patch: Partial<OverrideForm>) {
    setForm((prev) => ({ ...prev, ...patch }));
  }

  function patchLookupField(
    patch: Partial<Pick<OverrideForm, "sportsbook" | "sourceMarketId" | "sourceSelectionId">>,
  ) {
    const next = { ...form, ...patch };
    if (catalogLookupChanged(lookupKey, next)) {
      lastPrefillKeyRef.current = null;
      clearOverrideJobState();
      setForm({ ...next, ...EMPTY_OVERRIDE_FIELDS, mappingSource: "" });
      return;
    }
    setForm(next);
  }

  function runLookup() {
    if (!canLookup) return;
    clearOverrideJobState();

    const lookupForm = prepareCatalogLookup(form);

    const nextKey = buildLookupKey(lookupForm);
    if (lookupKeysEqual(lookupKey, nextKey)) {
      if (lookupForm.sourceSelectionId !== form.sourceSelectionId) {
        setForm(lookupForm);
      }
      void lookup.refetch();
      return;
    }
    lastPrefillKeyRef.current = null;
    setForm({ ...lookupForm, ...EMPTY_OVERRIDE_FIELDS, mappingSource: "" });
    setLookupKey(nextKey);
  }

  function publish(active: boolean) {
    override.mutate({
      sportsbook: form.sportsbook,
      game_id: form.gameId.trim(),
      market_id: form.marketId.trim(),
      selection: form.selection.trim(),
      selection_line: form.selectionLine.trim(),
      points: Number.isFinite(form.points) ? form.points : 0,
      selection_points: Number.isFinite(form.selectionPoints) ? form.selectionPoints : 0,
      grouping_key: form.groupingKey.trim(),
      source_market_id: form.sourceMarketId.trim(),
      source_selection_id: form.sourceSelectionId.trim(),
      mapping_source: form.mappingSource.trim() || undefined,
      reason: form.reason.trim(),
      active,
    });
  }

  if (meta?.catalog_enabled === false) {
    return <Navigate to="/entry" replace />;
  }

  return (
    <div>
      <PageHeader
        title="Catalog"
        description="Look up opticodds_mapping RFQ winners and publish mapping_override rows. Propagation runs asynchronously after publish."
      >
        <RefreshButton onClick={() => runLookup()} disabled={!lookupKey || lookupBusy} />
      </PageHeader>

      <section className="mb-8 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Lookup RFQ key</h2>
        <form
          className="grid gap-3 md:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault();
            runLookup();
          }}
        >
          <label className="text-sm">
            Sportsbook
            <select
              className="mt-1 w-full rounded border px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
              value={form.sportsbook}
              onChange={(e) => patchLookupField({ sportsbook: e.target.value })}
            >
              {SPORTSBOOKS.map((book) => (
                <option key={book} value={book}>{book}</option>
              ))}
            </select>
          </label>
          <label className="text-sm md:col-span-2">
            Source market id
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.sourceMarketId}
              onChange={(e) => patchLookupField({ sourceMarketId: e.target.value })}
              placeholder="KX… or Poly ticker"
            />
          </label>
          <label className="text-sm">
            Source selection id
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.sourceSelectionId}
              onChange={(e) => patchLookupField({ sourceSelectionId: e.target.value })}
              placeholder="yes, BERSCA, …"
            />
          </label>
          <div className="md:col-span-4">
            <button
              type="submit"
              className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              disabled={!canLookup}
            >
              Look up winner
            </button>
          </div>
        </form>
        {lookupBusy && (
          <p className="mt-4 rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300">
            Looking up …
          </p>
        )}
        {laneKeyHint(form.sportsbook, meta?.override_lane_enabled) && (
          <p className="mt-3 text-sm text-amber-800 dark:text-amber-200">
            {laneKeyHint(form.sportsbook, meta?.override_lane_enabled)}
          </p>
        )}
        {lookupErrorReason && (
          <p className="mt-3 text-sm text-red-600">{lookupErrorReason}</p>
        )}
        {lookupRequested && lookup.isSuccess && lookup.data && !lookupBusy && lookupCurrent && (
          <div className={`mt-4 rounded border p-3 text-sm ${lookupFeedbackClass(lookup.data)}`}>
            <div className="font-semibold">{lookup.data.rfq_key}</div>
            <p className="mt-1">
              {lookup.data.lookup_note ?? "Lookup completed."}
            </p>
            {lookup.data.candidate_count > 0 && (
              <p className="mt-1 text-xs opacity-80">
                {lookup.data.candidate_count} candidate
                {lookup.data.candidate_count === 1 ? "" : "s"}
                {lookup.data.in_rank_window !== true ? " (outside rank window)" : ""}
              </p>
            )}
          </div>
        )}
        {winner && !lookupBusy && lookupCurrent && (
          <div className={`mt-4 rounded border p-3 text-sm ${winnerPanelClass(lookup.data?.in_rank_window)}`}>
            <div className="font-semibold">
              {winnerPanelTitle(winner, lookup.data?.in_rank_window)}
            </div>
            <CatalogRowSummary row={winner} />
          </div>
        )}
        {lookup.isSuccess && !lookupBusy && lookupCurrent && candidates.length > 1 && (
          <div className="mt-4 space-y-3">
            <div className="text-sm font-semibold text-slate-600">
              {candidates.length} candidates (rank tie)
            </div>
            {candidates.map((candidate, index) => (
              <div
                key={`${String(candidate.game_id ?? "row")}-${index}`}
                className="rounded border p-3 text-sm dark:border-slate-700"
              >
                <div className="font-semibold">Candidate {index + 1}</div>
                <CatalogRowSummary row={candidate} />
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Publish override</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            game_id
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.gameId}
              onChange={(e) => patchForm({ gameId: e.target.value })}
            />
          </label>
          <label className="text-sm">
            market_id (Optic)
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.marketId}
              onChange={(e) => patchForm({ marketId: e.target.value })}
            />
          </label>
          <label className="text-sm md:col-span-2">
            selection
            <input
              className="mt-1 w-full rounded border px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
              value={form.selection}
              onChange={(e) => patchForm({ selection: e.target.value })}
            />
          </label>
          <label className="text-sm">
            selection_line
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.selectionLine}
              onChange={(e) => patchForm({ selectionLine: e.target.value })}
            />
          </label>
          <label className="text-sm">
            points / selection_points
            <div className="mt-1 flex gap-2">
              <input
                type="number"
                step="any"
                className="w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
                value={Number.isFinite(form.points) ? form.points : ""}
                onChange={(e) => patchForm({
                  points: e.target.value === "" ? Number.NaN : Number(e.target.value),
                })}
              />
              <input
                type="number"
                step="any"
                className="w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
                value={Number.isFinite(form.selectionPoints) ? form.selectionPoints : ""}
                onChange={(e) => patchForm({
                  selectionPoints: e.target.value === "" ? Number.NaN : Number(e.target.value),
                })}
              />
            </div>
          </label>
          <label className="text-sm md:col-span-2">
            grouping_key
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.groupingKey}
              onChange={(e) => patchForm({ groupingKey: e.target.value })}
            />
          </label>
          <label className="text-sm md:col-span-2">
            mapping_source
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
              value={form.mappingSource}
              onChange={(e) => patchForm({ mappingSource: e.target.value })}
              placeholder="HENRY, ORIGINAL, … (blank → ORIGINAL on merge)"
            />
          </label>
          <label className="text-sm md:col-span-2">
            reason
            <input
              className="mt-1 w-full rounded border px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
              value={form.reason}
              onChange={(e) => patchForm({ reason: e.target.value })}
            />
          </label>
        </div>
        {!lookupKeysMatch && lookupKey && (
          <p className="mt-3 text-sm text-amber-800 dark:text-amber-200">
            Lookup fields changed. Run Look up winner again before publishing.
          </p>
        )}
        {formIssuesReason && (
          <p className="mt-3 text-sm text-amber-800 dark:text-amber-200">
            {formIssuesReason}
          </p>
        )}
        {rankWindowWarning && (
          <p className="mt-3 text-sm text-amber-800 dark:text-amber-200">
            {rankWindowWarning}
          </p>
        )}
        {unreadReason && (
          <p className="mt-3 text-sm text-amber-800 dark:text-amber-200" role="status">
            Publishing is off for {form.sportsbook}: {unreadReason} Deactivating an existing override is still allowed.
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded bg-emerald-700 px-3 py-2 text-sm text-white disabled:opacity-50"
            disabled={override.isPending || !canPublishOverride || Boolean(unreadReason)}
            onClick={() => publish(true)}
          >
            Publish override
          </button>
          <button
            type="button"
            className="rounded border px-3 py-2 text-sm disabled:opacity-50 dark:border-slate-600"
            disabled={override.isPending || !canPublishOverride}
            onClick={() => publish(false)}
          >
            Deactivate override
          </button>
        </div>
        {overrideError && (
          <p className="mt-3 text-sm text-red-600">{overrideError}</p>
        )}
        {job.isError && (
          <p className="mt-3 text-sm text-red-600">{(job.error as Error).message}</p>
        )}
        {job.data && (
          <div className="mt-4 rounded border p-3 text-sm dark:border-slate-700">
            <div className="font-semibold">{job.data.status}</div>
            <p className="mt-1">{job.data.message}</p>
            {job.data.steps && <JobStepsSummary steps={job.data.steps} />}
            {job.data.lookup?.winner && (
              <div className="mt-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Post-job lookup
                </div>
                <CatalogRowSummary row={job.data.lookup.winner as Record<string, unknown>} />
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
