import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { isTerminalJob } from "@/lib/status-text";

import { ApiError } from "./errors";
import { get, post } from "./client";
import type { Job } from "./types";

export const JOB_POLL_MS = 2000;

/** Consecutive failed fetches after which polling gives up. */
export const MAX_POLL_FAILURES = 5;

type PollQuery<T> = {
  state: { data: T | undefined; error: unknown; errorUpdateCount: number; dataUpdatedAt: number };
};

/** TanStack exposes only a cumulative errorUpdateCount (fetchFailureCount resets at every fetch). To
 * count CONSECUTIVE failures we remember, per cached query, the errorUpdateCount seen when the latest
 * success landed (identified by a changed dataUpdatedAt). refetchInterval runs after every state
 * change, so the baseline is refreshed after each success, and reading it is idempotent. */
const baselines = new WeakMap<object, { dataUpdatedAt: number; errors: number }>();

function consecutiveFailures(query: PollQuery<unknown>): number {
  const { dataUpdatedAt, errorUpdateCount } = query.state;
  let base = baselines.get(query);
  if (!base || base.dataUpdatedAt !== dataUpdatedAt) {
    // Never succeeded (dataUpdatedAt 0): every error so far counts.
    base = { dataUpdatedAt, errors: dataUpdatedAt === 0 ? 0 : errorUpdateCount };
    baselines.set(query, base);
  }
  return errorUpdateCount - base.errors;
}

/** Polling rule shared by every polled query: stop when isDone(data), on a 4xx answer other than 408/429 (the
 * thing is gone or forbidden; asking again changes nothing), and after MAX_POLL_FAILURES consecutive errors.
 * A 5xx or network blip keeps polling, and a success resets the failure count. */
export function shouldPoll<T>(query: PollQuery<T>, pollMs: number, isDone: (data: T | undefined) => boolean): number | false {
  if (isDone(query.state.data)) return false;
  const error = query.state.error;
  // 408 and 429 are transient: keep polling (counted as failures like a 5xx).
  if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) return false;
  if (consecutiveFailures(query) >= MAX_POLL_FAILURES) return false;
  return pollMs;
}

export const jobQueryOptions = (jobId: string, pollMs = JOB_POLL_MS) =>
  queryOptions({
    queryKey: ["job", jobId] as const,
    queryFn: ({ signal }) => get<Job>(`/api/v1/jobs/${jobId}`, undefined, signal),
    // Poll until the job is over; a finished job is fetched once and then left alone.
    refetchInterval: (query) => shouldPoll(query, pollMs, (job) => isTerminalJob(job?.status)),
    staleTime: 0,
  });

/** The job, polled. When it turns terminal the tender's documents are refreshed once, because the
 * version's processing_status (and its extraction jobs) change with it. */
export function useJob(jobId: string, tenderId: string, pollMs?: number, versionStatus?: string) {
  const queryClient = useQueryClient();
  const query = useQuery(jobQueryOptions(jobId, pollMs));
  const status = query.data?.status;
  const previous = useRef<string | undefined>(undefined);
  useEffect(() => {
    // Only a real change refreshes the documents, not mounting a finished job: running -> finished,
    // and waiting -> running (the version turns "processing" then, which also clears a stale "failed"
    // after a retry). Default invalidation cancels an in-flight fetch that may have read old data.
    const before = previous.current;
    const finished = before !== undefined && !isTerminalJob(before) && isTerminalJob(status);
    const started = before === "queued" && status === "running";
    if (finished || started) void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] });
    previous.current = status;
  }, [status, tenderId, queryClient]);
  // Self-heal: the ingest job is over but the version row still says pending/processing (the job
  // finished before this card's first poll, so no transition was seen). Refresh once per distinct
  // (job status, version status) pair, so a server that keeps returning the stale value cannot loop.
  const stale = isTerminalJob(status) && (versionStatus === "pending" || versionStatus === "processing");
  useEffect(() => {
    if (stale) void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] });
  }, [stale, status, versionStatus, tenderId, queryClient]);
  return query;
}

export function useRetryJob(tenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => post<Job>(`/api/v1/jobs/${jobId}/retry`),
    onSuccess: (job) => {
      queryClient.setQueryData(["job", job.id], job);
      void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] });
    },
  });
}
