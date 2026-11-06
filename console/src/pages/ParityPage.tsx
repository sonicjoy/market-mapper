import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { checkParity, getMeta, listParity, reseedStatus, startReseed } from "../api";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import type { ParityEvent, ParityMismatchRow } from "../types";

function mismatchCount(ev: ParityEvent): number {
  if (typeof ev.mismatch_count === "number") {
    return ev.mismatch_count;
  }
  const n = ev.payload?.mismatch_count;
  return typeof n === "number" ? n : 0;
}

function ruleSetId(ev: ParityEvent): string {
  if (typeof ev.rule_set_id === "string" && ev.rule_set_id) {
    return ev.rule_set_id;
  }
  const fromPayload = ev.payload?.rule_set_id;
  return typeof fromPayload === "string" ? fromPayload : "—";
}

const DECLARATIVE_TYPES = ["rule_parity_ok", "rule_parity_mismatch"];
const ALIGNMENT_TYPES = ["tip_alignment_ok", "tip_alignment_stale"];
const BOOKS = ["crypto.com", "polymarket", "kalshi", "optic", "px"] as const;

function stringField(ev: ParityEvent, key: string): string {
  const value = ev.payload?.[key];
  return typeof value === "string" && value ? value : "—";
}

function missingLeagues(ev: ParityEvent): string[] {
  const value = ev.payload?.missing_leagues;
  return Array.isArray(value) ? value.filter((lg): lg is string => typeof lg === "string") : [];
}

function parseMismatchLine(line: string): ParityMismatchRow {
  const idx = line.indexOf(":");
  const league = idx >= 0 ? line.slice(0, idx).trim() : "";
  const rest = idx >= 0 ? line.slice(idx + 1).toLowerCase() : line.toLowerCase();
  const sportsbook = BOOKS.find((book) => rest.includes(book)) ?? "—";
  return { league: league || "—", sportsbook, detail: line };
}

function latestMismatchRows(events: ParityEvent[], fromApi?: ParityMismatchRow[]): ParityMismatchRow[] {
  if (fromApi !== undefined) {
    return fromApi;
  }
  const latest = events.find((ev) => DECLARATIVE_TYPES.includes(ev.event_type ?? ""));
  if (!latest || latest.event_type === "rule_parity_ok" || mismatchCount(latest) === 0) {
    return [];
  }
  const lines = latest.payload?.mismatches;
  if (!Array.isArray(lines)) {
    return [];
  }
  return lines.filter((line): line is string => typeof line === "string").map(parseMismatchLine);
}

type ParityStatus =
  | { kind: "never" }
  | { kind: "ok"; occurredAt: string; ruleSetId: string }
  | { kind: "mismatch"; occurredAt: string; ruleSetId: string; count: number };

type AlignmentStatus =
  | { kind: "unknown" }
  | { kind: "aligned"; occurredAt: string; servedId: string }
  | {
      kind: "stale";
      occurredAt: string;
      servedId: string;
      seedId: string;
      missing: string[];
    };

function parityStatus(events: ParityEvent[]): ParityStatus {
  const declarative = events.filter((ev) => DECLARATIVE_TYPES.includes(ev.event_type ?? ""));
  if (declarative.length === 0) {
    return { kind: "never" };
  }
  const latest = declarative[0];
  const occurredAt = latest.occurred_at ?? "—";
  const rs = ruleSetId(latest);
  const count = mismatchCount(latest);
  if (latest.event_type === "rule_parity_ok" || count === 0) {
    return { kind: "ok", occurredAt, ruleSetId: rs };
  }
  return { kind: "mismatch", occurredAt, ruleSetId: rs, count };
}

function alignmentStatus(events: ParityEvent[]): AlignmentStatus {
  const latest = events.find((ev) => ALIGNMENT_TYPES.includes(ev.event_type ?? ""));
  if (!latest) {
    return { kind: "unknown" };
  }
  const occurredAt = latest.occurred_at ?? "—";
  const servedId = stringField(latest, "served_rule_set_id");
  if (latest.event_type === "tip_alignment_ok") {
    return { kind: "aligned", occurredAt, servedId };
  }
  return {
    kind: "stale",
    occurredAt,
    servedId,
    seedId: stringField(latest, "latest_seed_rule_set_id"),
    missing: missingLeagues(latest),
  };
}

function AlignmentBanner({ status }: { status: AlignmentStatus }) {
  switch (status.kind) {
    case "unknown":
      return null;
    case "aligned":
      return (
        <div className="mb-4 notice-brand text-sm">
          Served tip matches the latest seed (checked {status.occurredAt}) · rule set{" "}
          <span className="font-mono text-xs">{status.servedId}</span>
        </div>
      );
    case "stale":
      return (
        <div className="mb-4 notice-amber text-sm">
          Served tip <span className="font-mono text-xs">{status.servedId}</span> is behind the
          latest seed <span className="font-mono text-xs">{status.seedId}</span> (checked{" "}
          {status.occurredAt})
          {status.missing.length > 0 && (
            <>
              {" "}
              · {status.missing.length} league{status.missing.length === 1 ? "" : "s"} missing:{" "}
              <span className="font-mono text-xs">{status.missing.join(", ")}</span>
            </>
          )}
        </div>
      );
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}

function StatusBanner({ status }: { status: ParityStatus }) {
  switch (status.kind) {
    case "never":
      return (
        <div className="mb-4 notice-amber text-sm">
          Parity has never run. Empty history does not mean Python and BQ agree — dual-read has
          not recorded a check yet.
        </div>
      );
    case "ok":
      return (
        <div className="mb-4 notice-brand text-sm">
          No mismatches (last checked {status.occurredAt}) · rule set{" "}
          <span className="font-mono text-xs">{status.ruleSetId}</span>
        </div>
      );
    case "mismatch":
      return (
        <div className="mb-4 notice-red text-sm">
          {status.count} mismatch{status.count === 1 ? "" : "es"} (last checked {status.occurredAt})
          · rule set <span className="font-mono text-xs">{status.ruleSetId}</span>
        </div>
      );
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}

function reseedNote(
  status: "running" | "ok" | "error",
  data: { already_loaded?: boolean; rule_set_id?: string | null; error?: string },
): string {
  switch (status) {
    case "running":
      return "Re-seeding…";
    case "ok":
      return data.already_loaded
        ? `Already loaded — activated: ${data.rule_set_id ?? ""}`
        : `Done and activated: ${data.rule_set_id ?? ""}`;
    case "error":
      return `Failed: ${data.error ?? "error"}`;
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}

export function ParityPage() {
  const { data: meta } = useQuery({
    queryKey: ["meta"],
    queryFn: getMeta,
  });
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["parity"],
    queryFn: listParity,
  });
  const [jobId, setJobId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [starting, setStarting] = useState(false);
  const [checking, setChecking] = useState(false);
  const actionLock = useRef(false);

  const jobQuery = useQuery({
    queryKey: ["reseed", jobId],
    queryFn: () => reseedStatus(jobId ?? ""),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });

  useEffect(() => {
    const row = jobQuery.data;
    if (!row) {
      return;
    }
    setNote(reseedNote(row.status, row));
    if (row.status === "ok") {
      setJobId(null);
      void refetch();
    }
    if (row.status === "error") {
      setJobId(null);
    }
  }, [jobQuery.data, refetch]);

  const events = (data?.events ?? []) as ParityEvent[];
  const status = parityStatus(events);
  const alignment = alignmentStatus(events);
  const rows = latestMismatchRows(events, data?.latest_mismatches);
  const actionBusy = starting || checking || Boolean(jobId);
  const busy = actionBusy || isFetching;

  async function onCheck() {
    if (actionLock.current || busy) {
      return;
    }
    actionLock.current = true;
    setChecking(true);
    setNote("Re-checking served tip…");
    try {
      await checkParity();
      setNote("Reset against the served tip (no re-seed).");
      await refetch();
    } catch (err) {
      setNote(`Failed: ${err instanceof Error ? err.message : "error"}`);
    } finally {
      setChecking(false);
      actionLock.current = false;
    }
  }

  async function onReseed() {
    if (actionLock.current || busy) {
      return;
    }
    actionLock.current = true;
    setStarting(true);
    setNote("Re-seeding…");
    try {
      const started = await startReseed();
      setJobId(started.job_id);
    } catch (err) {
      setNote(`Failed: ${err instanceof Error ? err.message : "error"}`);
    } finally {
      setStarting(false);
      actionLock.current = false;
    }
  }

  return (
    <div>
      <PageHeader
        title="Parity"
        description={
          meta?.env === "test"
            ? "Python vs the served (activated) BQ tip. Reset re-runs that check without writing a snapshot. Re-seed writes a new snapshot and activates it."
            : "Python vs the served (activated) BQ tip. Reset re-runs that check without writing a snapshot."
        }
      >
        <RefreshButton busy={isFetching} disabled={actionBusy} onClick={() => refetch()} />
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void onCheck()}
          disabled={busy}
          aria-busy={checking}
        >
          {checking ? "Resetting…" : "Reset"}
        </button>
        {meta?.env === "test" ? (
          <button
            type="button"
            className="btn-primary"
            onClick={() => void onReseed()}
            disabled={busy}
            aria-busy={starting || Boolean(jobId)}
          >
            {starting || jobId ? "Re-seeding…" : "Re-seed"}
          </button>
        ) : null}
      </PageHeader>
      {note ? <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">{note}</p> : null}
      {isLoading && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          {error instanceof Error ? error.message : "Failed to load parity events."}
        </p>
      )}
      {data && (
        <>
          <StatusBanner status={status} />
          <AlignmentBanner status={alignment} />
          <div className="panel">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-3 py-2">League</th>
                  <th className="px-3 py-2">Sportsbook</th>
                  <th className="px-3 py-2">Mismatch</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={`${row.league}-${i}`} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="px-3 py-2 font-mono text-xs">{row.league}</td>
                    <td className="px-3 py-2 font-mono text-xs">{row.sportsbook}</td>
                    <td className="px-3 py-2 font-mono text-xs whitespace-pre-wrap break-all">
                      {row.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {status.kind === "never" && (
              <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">
                No declarative parity events recorded.
              </p>
            )}
            {status.kind === "ok" && rows.length === 0 && (
              <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">
                No mismatches in the latest dual-read check.
              </p>
            )}
            {status.kind === "mismatch" && rows.length === 0 && (
              <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">
                Latest check reported mismatches but no detail lines were stored.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
