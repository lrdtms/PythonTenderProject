"use client";

import { type UseMutationResult, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/api/errors";
import { anyJobActive, extractionQueryOptions, useCancelJob, useRequestExtraction } from "@/api/extraction";
import type { Job, KindStatus } from "@/api/types";
import {
  attemptText,
  cancelFailureText,
  isTerminalJob,
  jobErrorText,
  jobStatusLabel,
  jobTone,
  kindLabel,
  progressBounds,
  progressText,
  warningText,
} from "@/lib/status-text";

import { useCan } from "./auth-gate";
import { StaleNote } from "./stale-note";
import { StatusBadge } from "./status-badge";

const REFUSALS: Record<string, string> = {
  extraction_options_conflict: "An extraction with different options is already running. Wait for it to finish.",
  tender_archived: "This tender is archived, so nothing can be extracted.",
  not_processed: "The document has not finished processing yet.",
};

/** Rows kept as already reviewed on a re-run are not in `items`; add them back so the total is honest. */
function keptCount(warnings: unknown[]): number {
  for (const w of warnings) {
    if (typeof w !== "object" || w === null) continue;
    const { code, count } = w as { code?: unknown; count?: unknown };
    if (code === "DUPLICATE_OF_REVIEWED" && typeof count === "number" && Number.isInteger(count) && count > 0) return count;
  }
  return 0;
}

function countText(kind: string, counts: Record<string, unknown>, kept = 0): string | null {
  const n = (key: string) => (typeof counts[key] === "number" ? (counts[key] as number) : null);
  if (kind === "boq") {
    const items = n("items");
    if (items === null) return null;
    const total = items + kept;
    return `${total} ${total === 1 ? "line" : "lines"}${kept > 0 ? ` (${kept} kept as reviewed)` : ""}`;
  }
  if (kind === "quotation") {
    const items = n("items");
    if (items === null) return null;
    const total = items + kept;
    return `${total} ${total === 1 ? "item" : "items"}${kept > 0 ? ` (${kept} kept as reviewed)` : ""}`;
  }
  const count = n("requirements");
  return count === null ? null : `${count} ${count === 1 ? "requirement" : "requirements"}`;
}

function JobBar({ kind, job }: { kind: string; job: Job }) {
  const text = progressText(kind, job);
  const attempt = attemptText(job.attempt_count);
  const { done, total } = progressBounds(job);
  const determinate = job.status === "running" && total > 0;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[var(--ink)]">
      <progress
        aria-label={`${kindLabel(kind)} extraction progress`}
        className="align-middle"
        {...(determinate ? { value: done, max: total } : {})}
      />
      {text ? <span>{text}</span> : null}
      {attempt ? <span className="text-zinc-500 dark:text-zinc-400">{attempt}</span> : null}
    </div>
  );
}

const BUTTON = "btn btn-sm";

/** Cancel for an active job, with an inline confirmation. Only one row's cancel is in flight at a time. */
function CancelControl({ job, cancel }: { job: Job; cancel: UseMutationResult<Job, Error, string> }) {
  const [confirming, setConfirming] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);
  const cancelling = cancel.isPending && cancel.variables === job.id;
  if (!confirming) {
    return (
      <button type="button" disabled={cancel.isPending} className={BUTTON} onClick={() => setConfirming(true)}>
        Cancel
      </button>
    );
  }
  return (
    <span role="group" aria-label="Confirm cancellation" aria-live="polite" className="flex flex-wrap items-center gap-2 rounded-lg bg-[var(--sheet)] p-2">
      <span>Cancel this extraction? Work already done on this run is discarded.</span>
      <button
        ref={confirmRef}
        type="button"
        disabled={cancel.isPending}
        className={BUTTON}
        onClick={() => cancel.mutate(job.id, { onSettled: () => setConfirming(false) })}
      >
        Yes, cancel
      </button>
      <button type="button" disabled={cancel.isPending} className={BUTTON} onClick={() => setConfirming(false)}>
        Keep going
      </button>
      {cancelling ? <span className="text-zinc-600 dark:text-zinc-400">Cancelling…</span> : null}
    </span>
  );
}

function KindRow({
  item,
  canCancel,
  cancel,
}: {
  item: KindStatus;
  canCancel: boolean;
  cancel: UseMutationResult<Job, Error, string>;
}) {
  const job = item.job;
  const cancelable = canCancel && job !== null && !isTerminalJob(job.status);
  const cancelFailed = job !== null && cancel.isError && cancel.variables === job.id;
  const warnings = [...(job?.warnings ?? []), ...(item.run?.warnings ?? [])];
  const counts = item.run?.counts
    ? countText(item.kind, item.run.counts as Record<string, unknown>, keptCount(item.run.warnings ?? job?.warnings ?? []))
    : null;
  const seen = new Set<string>();
  const unique = warnings.map(warningText).filter((t) => (seen.has(t) ? false : (seen.add(t), true)));
  return (
    <li className="space-y-1 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{kindLabel(item.kind)}</span>
        {job ? <StatusBadge tone={jobTone(job.status)} label={jobStatusLabel(job.status)} /> : null}
        {counts ? <span>{counts}</span> : null}
        {cancelable && job ? <CancelControl job={job} cancel={cancel} /> : null}
      </div>
      {job && progressText(item.kind, job) !== null ? <JobBar kind={item.kind} job={job} /> : null}
      {job?.status === "failed" ? <p className="text-red-700 dark:text-red-300">{jobErrorText(job.error_code)}</p> : null}
      {cancelFailed ? (
        <p role="alert" className="text-red-700 dark:text-red-300">
          {cancelFailureText(cancel.error instanceof ApiError ? cancel.error.code : null)}
        </p>
      ) : null}
      {unique.length > 0 ? (
        <ul className="list-disc pl-5 text-amber-800 dark:text-amber-300">
          {unique.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

type Props = { versionId: string; ready: boolean; archived?: boolean; pollMs?: number };

export function ExtractionPanel({ versionId, ready, archived = false, pollMs }: Props) {
  const canRun = useCan("review_data") && !archived;
  const status = useQuery({ ...extractionQueryOptions(versionId, pollMs), enabled: ready });
  const request = useRequestExtraction(versionId);
  const cancel = useCancelJob(versionId);
  const [deep, setDeep] = useState(false);
  if (!ready) return null;
  if (status.isPending) return <p role="status" className="text-sm text-zinc-500">Checking extraction…</p>;
  if (!status.data) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {status.error instanceof ApiError ? status.error.message : "Could not load the extraction status."}
      </p>
    );
  }
  const kinds = status.data.kinds.filter((k) => k.job || k.run);
  const busy = anyJobActive(status.data) || request.isPending;
  const refusal = request.error instanceof ApiError ? (REFUSALS[request.error.code] ?? request.error.message) : request.error ? "Could not start the extraction." : null;

  return (
    <div className="rounded-lg bg-[var(--raised)] p-3">
      <h3 className="text-sm font-semibold">Extraction</h3>
      {status.error ? <StaleNote message="Could not refresh the status." onCheckAgain={() => void status.refetch()} /> : null}
      {kinds.length === 0 ? <p className="py-2 text-sm text-zinc-600 dark:text-zinc-400">Extraction has not run yet.</p> : null}
      {kinds.length > 0 ? (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {kinds.map((k) => (
            <KindRow key={k.kind} item={k} canCancel={canRun} cancel={cancel} />
          ))}
        </ul>
      ) : null}
      {refusal ? <p role="alert" className="mt-2 text-sm text-red-600">{refusal}</p> : null}
      {canRun ? (
        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} disabled={busy} />
            Deep scan (slower, reads every section)
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => request.mutate(deep)}
            className="btn"
          >
            {request.isPending ? "Starting…" : "Run extraction again"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
