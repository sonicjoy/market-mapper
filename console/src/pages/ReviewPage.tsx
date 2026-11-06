import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { combinePipelineReview, listReview, listReviewRecent } from "../api";
import { PageHeader } from "../components/PageHeader";
import { RefreshButton } from "../components/RefreshButton";
import { publishReviewView } from "../consoleView";
import {
  reviewStatusBadgeClass,
  showsReviewBadge,
  waitingReviewLabel,
} from "../lib/reviewQueue";
import type { ReviewCard, ReviewHistoryRow } from "../types";

const PIPELINE_PROPOSER = "pipeline-gap-fix";

function pipelineCardCount(cards: ReviewCard[] | undefined): number {
  return (cards ?? []).filter((card) => card.proposer === PIPELINE_PROPOSER).length;
}

function formatProposalAt(iso: string): string {
  if (!iso) {
    return "—";
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return parsed.toLocaleString();
}

function RecentProposalsTable({ rows }: { rows: ReviewHistoryRow[] }) {
  if (!rows.length) {
    return null;
  }
  return (
    <section className="mt-8">
      <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
        Recent proposals
      </h2>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">ID</th>
              <th className="px-3 py-2 font-medium">Brief</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Reviewer</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((row) => (
              <tr key={row.ref} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500 dark:text-slate-400">
                  {formatProposalAt(row.at)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                  <Link to={`/review/${row.ref}`} className="text-brand-600 hover:underline dark:text-brand-400">
                    {row.ref}
                  </Link>
                </td>
                <td className="px-3 py-2 text-xs">{row.brief}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  {showsReviewBadge(row.status) ? (
                    <span className={reviewStatusBadgeClass(row.status)}>
                      {waitingReviewLabel(row.status)}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-500">{row.status}</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                  {row.reviewer ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ReviewPage() {
  const qc = useQueryClient();
  const combineAttempted = useRef(false);
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["review"],
    queryFn: listReview,
  });
  const {
    data: recent,
    isLoading: recentLoading,
    isError: recentError,
    refetch: refetchRecent,
  } = useQuery({
    queryKey: ["review", "recent"],
    queryFn: () => listReviewRecent(10),
  });
  const combine = useMutation({
    mutationFn: combinePipelineReview,
    onSuccess: (cards) => {
      qc.setQueryData(["review"], cards);
      void qc.invalidateQueries({ queryKey: ["review", "recent"] });
    },
  });

  const { mutate, isPending } = combine;

  useEffect(() => {
    publishReviewView("/review");
  }, []);

  useEffect(() => {
    if (pipelineCardCount(data) < 2 || combineAttempted.current || isPending) {
      return;
    }
    combineAttempted.current = true;
    mutate();
  }, [data, isPending, mutate]);

  return (
    <div>
      <PageHeader
        title="Proposed"
        description="Pending mapping proposals — open one to review pins by fixture."
      >
        <RefreshButton
          busy={isFetching || isPending}
          onClick={() => {
            combineAttempted.current = false;
            void refetch();
            void refetchRecent();
          }}
        />
      </PageHeader>
      {isLoading && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}
      {isPending && <p className="text-sm text-slate-500 dark:text-slate-400">Merging pipeline cards…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          {error instanceof Error ? error.message : "Failed to load review queue."}
        </p>
      )}
      <div className="space-y-2">
        {(data ?? []).map((card) => (
          <Link
            key={card.ref}
            to={`/review/${card.ref}`}
            className="card block hover:border-brand-300 dark:hover:border-brand-600"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-medium">{card.headline || card.summary}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {[card.league_label, [card.sportsbook_label, card.code].filter(Boolean).join(" "), card.proposer]
                    .filter((part) => part.trim())
                    .join(" · ")}
                </div>
                {card.mappings?.length ? (
                  <div className="mt-1 text-xs text-slate-500">
                    {card.mappings.length} mapping row(s)
                  </div>
                ) : null}
              </div>
              {showsReviewBadge(card.status) && (
                <span className={reviewStatusBadgeClass(card.status)}>
                  {waitingReviewLabel(card.status)}
                </span>
              )}
            </div>
          </Link>
        ))}
        {!isLoading && (data ?? []).length === 0 ? (
          <p className="text-sm text-slate-500">No open proposals.</p>
        ) : null}
      </div>
      {recentLoading && (
        <p className="mt-6 text-sm text-slate-500 dark:text-slate-400">Loading recent proposals…</p>
      )}
      {recentError && (
        <p className="mt-6 text-sm text-red-600">Failed to load recent proposals.</p>
      )}
      <RecentProposalsTable rows={recent ?? []} />
    </div>
  );
}
