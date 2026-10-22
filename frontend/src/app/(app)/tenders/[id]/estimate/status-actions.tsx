"use client";

import { useState } from "react";

import {
  type Estimate,
  useApproveEstimate,
  useCreateEstimate,
  useReopenEstimate,
  useReviewEstimate,
} from "@/api/estimates";
import { useCan } from "@/components/auth-gate";

import { ErrorNotice } from "./error-notice";

const BUTTON = "rounded border px-3 py-1 text-sm disabled:opacity-50";

/** Mark reviewed, Approve, Reopen and New version, shown by permission and by the state of the estimate. */
export function StatusActions({
  estimate,
  hasDraft,
  archived,
  onCreated,
}: {
  estimate: Estimate;
  hasDraft: boolean;
  archived: boolean;
  onCreated?: (id: string) => void;
}) {
  const canReview = useCan("review_data") && !archived;
  const canApprove = useCan("approve_estimate") && !archived;
  const review = useReviewEstimate();
  const reopen = useReopenEstimate();
  const approve = useApproveEstimate();
  const create = useCreateEstimate(estimate.tender_id);
  const [confirming, setConfirming] = useState(false);

  const all = [review, reopen, approve, create];
  const pending = all.some((m) => m.isPending);
  const error = all.map((m) => m.error).find((e) => e);
  const clear = () => all.forEach((m) => m.reset());

  const showReview = estimate.status === "draft" && canReview;
  const showApprove = estimate.status === "reviewed" && canApprove;
  const showReopen = estimate.status === "reviewed" && canReview;
  const showNew = !hasDraft && canReview;

  return (
    <div>
      <ErrorNotice error={error} />
      <div role="group" aria-label="Estimate actions" className="mb-4 flex flex-wrap items-center gap-2">
        {showReview ? (
          <button
            type="button"
            disabled={pending}
            className={BUTTON}
            onClick={() => {
              clear();
              review.mutate(estimate.id);
            }}
          >
            Mark reviewed
          </button>
        ) : null}
        {showApprove && !confirming ? (
          <button
            type="button"
            disabled={pending}
            className={BUTTON}
            onClick={() => {
              clear();
              setConfirming(true);
            }}
          >
            Approve
          </button>
        ) : null}
        {showApprove && confirming ? (
          <span role="group" aria-label="Confirm approval" className="flex flex-wrap items-center gap-2 rounded border p-2 text-sm">
            <span>Approve this estimate? It can no longer be changed.</span>
            <button
              type="button"
              disabled={pending}
              className={BUTTON}
              onClick={() => {
                clear();
                approve.mutate(estimate.id, { onSettled: () => setConfirming(false) });
              }}
            >
              Yes, approve
            </button>
            <button type="button" disabled={pending} className={BUTTON} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </span>
        ) : null}
        {showReopen ? (
          <button
            type="button"
            disabled={pending}
            className={BUTTON}
            onClick={() => {
              clear();
              reopen.mutate(estimate.id);
            }}
          >
            Reopen
          </button>
        ) : null}
        {showNew ? (
          <button
            type="button"
            disabled={pending}
            className={BUTTON}
            onClick={() => {
              clear();
              create.mutate(undefined, { onSuccess: (e) => onCreated?.(e.id) });
            }}
          >
            New version
          </button>
        ) : null}
      </div>
    </div>
  );
}
