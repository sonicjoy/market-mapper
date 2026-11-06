import type { ReviewCard } from "../types";

/** Human status from GET /review after validate succeeds. */
const WAITING = "waiting_for_checker";
/** Human status from GET /review while propose is still validating. */
const VALIDATING = "submitted";
/** Human status after approve (checker-only env). */
const APPROVED = "approved";
/** Human status after approve when allow_activate is on. */
const ACTIVATED = "activated";
/** Human status after reject. */
const REJECTED = "rejected";
const SUPERSEDE_INTO = "superseded: combined into ";

export function isValidatingReview(status: string): boolean {
  return status === VALIDATING;
}

export function isWaitingReview(status: string): boolean {
  return status === WAITING;
}

/** After Drop+trim, Approve only if the card is already validated. */
export function nextApproveAfterTrim(status: string): "approve" | "wait" {
  return isWaitingReview(status) ? "approve" : "wait";
}

export function isApprovedReview(status: string): boolean {
  return status === APPROVED || status === ACTIVATED;
}

export function isRejectedReview(status: string): boolean {
  return status === REJECTED;
}

export function supersededByRef(note: string | null | undefined): string | null {
  const text = (note ?? "").trim();
  if (text.startsWith(SUPERSEDE_INTO)) {
    const ref = text.slice(SUPERSEDE_INTO.length).trim();
    return ref || null;
  }
  const fromError = /Open the new card (\S+?)\.?$/.exec(text);
  return fromError?.[1] ?? null;
}

export function showsReviewBadge(status: string): boolean {
  return (
    isValidatingReview(status) ||
    isWaitingReview(status) ||
    isApprovedReview(status) ||
    isRejectedReview(status)
  );
}

export function waitingReviewLabel(status: string): string {
  if (isValidatingReview(status)) {
    return "Validation in progress...";
  }
  if (isWaitingReview(status)) {
    return "Needs approval";
  }
  if (isApprovedReview(status)) {
    return "Approved";
  }
  if (isRejectedReview(status)) {
    return "Rejected";
  }
  return status;
}

export function reviewStatusBadgeClass(status: string): string {
  const base = "rounded px-2 py-0.5 text-[10px] font-semibold";
  if (isApprovedReview(status)) {
    return `${base} bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300`;
  }
  if (isRejectedReview(status)) {
    return `${base} bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300`;
  }
  return `${base} bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300`;
}

export function waitingReviewCount(cards: ReviewCard[] | undefined): number {
  return (cards ?? []).filter((card) => isWaitingReview(card.status)).length;
}
