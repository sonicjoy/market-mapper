import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { approveReview, getReview, rejectReview } from "../api";
import { PageHeader } from "../components/PageHeader";
import { ProposedExplorer } from "../components/ProposedExplorer";
import { publishReviewView } from "../consoleView";
import { clearProposedViewState } from "../lib/proposedViewState";
import {
  isRejectedReview,
  isValidatingReview,
  isWaitingReview,
  reviewStatusBadgeClass,
  showsReviewBadge,
  supersededByRef,
  waitingReviewLabel,
} from "../lib/reviewQueue";

export function ReviewDetailPage() {
  const { ref = "" } = useParams();
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const [approveAfterValidate, setApproveAfterValidate] = useState(false);

  useEffect(() => {
    publishReviewView(`/review/${ref}`, ref);
  }, [ref]);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["review", ref],
    queryFn: () => getReview(ref),
    enabled: Boolean(ref),
    refetchInterval: (query) => {
      const status = query.state.data?.status ?? "";
      if (isValidatingReview(status) || approveAfterValidate) return 4000;
      if (isWaitingReview(status)) return 15_000;
      return false;
    },
  });

  const approve = useMutation({
    mutationFn: () => approveReview(ref),
    onSuccess: (card) => {
      clearProposedViewState(ref);
      qc.setQueryData(["review", ref], card);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
  });
  const reject = useMutation({
    mutationFn: () => rejectReview(ref, comment),
    onSuccess: (card) => {
      clearProposedViewState(ref);
      qc.setQueryData(["review", ref], card);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
  });

  useEffect(() => {
    if (!approveAfterValidate) return;
    const status = data?.status ?? "";
    if (isRejectedReview(status)) {
      setApproveAfterValidate(false);
      return;
    }
    if (isWaitingReview(status)) {
      setApproveAfterValidate(false);
      approve.mutate();
    }
  }, [approveAfterValidate, data?.status, approve]);

  useEffect(() => {
    if (!approveAfterValidate) return;
    const timer = window.setTimeout(() => setApproveAfterValidate(false), 90_000);
    return () => window.clearTimeout(timer);
  }, [approveAfterValidate]);

  if (isLoading) return <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>;
  if (isError || !data) return <p className="text-sm text-red-600">Not found.</p>;

  const waiting = isWaitingReview(data.status);
  const validating = isValidatingReview(data.status);
  const actionError = (approve.error || reject.error)?.message;
  const actionErrorText =
    actionError === "not_validated" || approveAfterValidate
      ? undefined
      : actionError;
  const supersededBy = supersededByRef(data.note) ?? supersededByRef(actionErrorText);
  const proposed = data.proposed;
  const allRows = proposed?.rows ?? data.mappings ?? [];

  return (
    <div>
      <PageHeader title="Proposed detail" description={<Link to="/review">← Back to queue</Link>} />
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{data.headline || data.summary}</h3>
          <p className="text-xs text-slate-500">{data.proposer}</p>
        </div>
        {showsReviewBadge(data.status) && (
          <span className={reviewStatusBadgeClass(data.status)}>
            {waitingReviewLabel(data.status)}
          </span>
        )}
      </div>
      {supersededBy ? (
        <p className="mb-3 text-sm text-amber-800 dark:text-amber-200">
          This harvest was superseded.{" "}
          <Link to={`/review/${supersededBy}`} className="font-medium underline">
            Open the new card
          </Link>
          {" · "}
          <Link to="/review" className="underline">
            All proposals
          </Link>
        </p>
      ) : isRejectedReview(data.status) ? (
        <p className="mb-3 text-sm text-amber-800 dark:text-amber-200">
          This harvest was rejected.{" "}
          <Link to="/review" className="font-medium underline">
            Open Proposed for the live card
          </Link>
        </p>
      ) : null}
      {proposed && proposed.leagues.length > 0 ? (
        <ProposedExplorer
          key={ref}
          proposalRef={ref}
          proposed={proposed}
          allRows={allRows}
          waiting={waiting}
          validating={validating || approveAfterValidate}
          onTrimmed={() => void refetch()}
          onApprove={() => approve.mutate()}
          approvePending={approve.isPending || approveAfterValidate}
          comment={comment}
          onComment={setComment}
          onReject={() => reject.mutate()}
          rejectPending={reject.isPending}
          onWaitThenApprove={() => {
            setApproveAfterValidate(true);
            void refetch();
          }}
        />
      ) : (
        <p className="text-sm text-slate-500">No structured mappings on this proposal.</p>
      )}
      {validating && (
        <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">Validation in progress...</p>
      )}
      {waiting && !(proposed && proposed.leagues.length > 0) ? (
        <div className="card mt-4 max-w-2xl space-y-3">
          <div>
            <label className="label" htmlFor="comment">
              Comment
            </label>
            <input
              id="comment"
              className="input"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-ghost"
              disabled={reject.isPending}
              onClick={() => reject.mutate()}
            >
              Reject
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={approve.isPending}
              onClick={() => approve.mutate()}
            >
              Approve
            </button>
          </div>
        </div>
      ) : null}
      {actionErrorText ? <p className="mt-2 text-sm text-red-600">{actionErrorText}</p> : null}
    </div>
  );
}
