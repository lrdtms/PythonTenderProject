"use client";

import { ApiError } from "@/api/errors";
import { useJob, useRetryJob } from "@/api/jobs";
import { isTerminalJob, jobErrorText, jobStatusLabel, jobTone, warningText } from "@/lib/status-text";

import { useCan } from "./auth-gate";
import { StaleNote } from "./stale-note";
import { StatusBadge } from "./status-badge";

type Props = { jobId: string; tenderId: string; pollMs?: number; archived?: boolean; versionStatus?: string };

export function JobProgress({ jobId, tenderId, pollMs, archived = false, versionStatus }: Props) {
  const { data: job, error, isPending, refetch } = useJob(jobId, tenderId, pollMs, versionStatus);
  const canRetry = useCan("upload_documents") && !archived;
  const retry = useRetryJob(tenderId);

  if (isPending) return <p role="status" className="text-sm text-zinc-500">Checking progress…</p>;
  if (!job) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {error instanceof ApiError ? error.message : "Could not load the progress."}
      </p>
    );
  }
  const active = !isTerminalJob(job.status);
  return (
    <div className="space-y-2 text-sm">
      {error ? <StaleNote message="Could not refresh the status." onCheckAgain={() => void refetch()} /> : null}
      <StatusBadge tone={jobTone(job.status)} label={jobStatusLabel(job.status)} />
      {active ? (
        <progress
          aria-label="Processing progress"
          className="ml-3 align-middle"
          {...(job.progress_total > 0 ? { value: job.progress_done, max: job.progress_total } : {})}
        />
      ) : null}
      {job.status === "failed" ? (
        <div role="alert" className="text-red-700 dark:text-red-300">
          <p>{jobErrorText(job.error_code)}</p>
          {canRetry ? (
            <button
              type="button"
              disabled={retry.isPending}
              onClick={() => {
                retry.reset();
                retry.mutate(job.id);
              }}
              className="mt-1 rounded border border-red-600 px-3 py-1 disabled:opacity-50"
            >
              {retry.isPending ? "Retrying…" : "Retry"}
            </button>
          ) : null}
        </div>
      ) : null}
      {retry.error && job.status === "failed" ? (
        <p role="alert" className="text-red-600">
          {retry.error instanceof ApiError ? retry.error.message : "Could not retry."}
        </p>
      ) : null}
      {job.warnings.length > 0 ? (
        <ul className="list-disc pl-5 text-amber-800 dark:text-amber-300">
          {job.warnings.map((w, i) => (
            <li key={i}>{warningText(w)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
