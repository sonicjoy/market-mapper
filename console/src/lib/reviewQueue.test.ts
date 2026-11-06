import { describe, expect, it } from "vitest";

import type { ReviewCard } from "../types";
import {
  isApprovedReview,
  isValidatingReview,
  isWaitingReview,
  nextApproveAfterTrim,
  reviewStatusBadgeClass,
  showsReviewBadge,
  supersededByRef,
  waitingReviewCount,
  waitingReviewLabel,
} from "./reviewQueue";

describe("reviewQueue", () => {
  it("treats submitted as validation in progress, not ready to approve", () => {
    expect(isValidatingReview("submitted")).toBe(true);
    expect(isWaitingReview("submitted")).toBe(false);
    expect(showsReviewBadge("submitted")).toBe(true);
    expect(waitingReviewLabel("submitted")).toBe("Validation in progress...");
  });

  it("keeps validated cards as needs approval", () => {
    expect(isWaitingReview("waiting_for_checker")).toBe(true);
    expect(isValidatingReview("waiting_for_checker")).toBe(false);
    expect(waitingReviewLabel("waiting_for_checker")).toBe("Needs approval");
    expect(nextApproveAfterTrim("waiting_for_checker")).toBe("approve");
    expect(nextApproveAfterTrim("submitted")).toBe("wait");
  });

  it("parses the live harvest ref from a supersede note or trim error", () => {
    expect(supersededByRef("superseded: combined into P_abc")).toBe("P_abc");
    expect(supersededByRef("This harvest was superseded. Open the new card P_abc.")).toBe("P_abc");
    expect(supersededByRef("rejected by operator")).toBeNull();
  });

  it("shows approved badge for approved and activated statuses", () => {
    expect(isApprovedReview("approved")).toBe(true);
    expect(isApprovedReview("activated")).toBe(true);
    expect(showsReviewBadge("approved")).toBe(true);
    expect(showsReviewBadge("activated")).toBe(true);
    expect(waitingReviewLabel("approved")).toBe("Approved");
    expect(waitingReviewLabel("activated")).toBe("Approved");
    expect(reviewStatusBadgeClass("approved")).toContain("emerald");
  });

  it("shows rejected badge", () => {
    expect(showsReviewBadge("rejected")).toBe(true);
    expect(waitingReviewLabel("rejected")).toBe("Rejected");
    expect(reviewStatusBadgeClass("rejected")).toContain("red");
  });

  it("counts only checker-ready cards in the nav badge", () => {
    const cards = [
      { status: "submitted" },
      { status: "waiting_for_checker" },
      { status: "approved" },
    ] as ReviewCard[];
    expect(waitingReviewCount(cards)).toBe(1);
  });
});
