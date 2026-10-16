import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { isTerminalJob } from "@/lib/status-text";

import { ApiError } from "./errors";
import { get, post } from "./client";
import type { Job } from "./types";

export const JOB_POLL_MS = 2000;

/** Failed fetches after which polling gives up. TanStack resets fetchFailureCount at the start of
 * every fetch (so it never exceeds 1 across refetches); errorUpdateCount is the cumulative count. */
export const MAX_POLL_FAILURES = 5;

/** Polling rule shared by every polled query: stop on a terminal job, on a 4xx answer (the thing
 * is gone or forbidden; asking again changes nothing), and after MAX_POLL_FAILURES errors. A 5xx or network blip keeps polling. */
export function shouldPoll(
  query: { state: { data: { status: string } | undefined; error: unknown; errorUpdateCount: number } },
  pollMs: number,
): number | false {
  if (isTerminalJob(query.state.data?.status)) return false;
  const error = query.state.error;
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  if (query.state.errorUpdateCount >= MAX_POLL_FAILURES) return false;
  return pollMs;
}

export const jobQueryOptions = (jobId: string, pollMs = JOB_POLL_MS) =>
  queryOptions({
    queryKey: ["job", jobId] as const,
    queryFn: ({ signal }) => get<Job>(`/api/v1/jobs/${jobId}`, undefined, signal),
    // Poll until the job is over; a finished job is fetched once and then left alone.
    refetchInterval: (query) => shouldPoll(query, pollMs),
    staleTime: 0,
  });

/** The job, polled. When it turns terminal the tender's documents are refreshed once, because the
 * version's processing_status (and its extraction jobs) change with it. */
export function useJob(jobId: string, tenderId: string, pollMs?: number) {
  const queryClient = useQueryClient();
  const query = useQuery(jobQueryOptions(jobId, pollMs));
  const status = query.data?.status;
  const previous = useRef<string | undefined>(undefined);
  useEffect(() => {
    // Only a real running -> finished transition refreshes the documents, not mounting a finished job.
    if (previous.current !== undefined && !isTerminalJob(previous.current) && isTerminalJob(status)) {
      void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] }, { cancelRefetch: false });
    }
    previous.current = status;
  }, [status, tenderId, queryClient]);
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
