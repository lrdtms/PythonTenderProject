import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { isTerminalJob } from "@/lib/status-text";

import { get, post } from "./client";
import type { Job } from "./types";

export const JOB_POLL_MS = 2000;

export const jobQueryOptions = (jobId: string, pollMs = JOB_POLL_MS) =>
  queryOptions({
    queryKey: ["job", jobId] as const,
    queryFn: ({ signal }) => get<Job>(`/api/v1/jobs/${jobId}`, undefined, signal),
    // Poll until the job is over; a finished job is fetched once and then left alone.
    refetchInterval: (query) => (isTerminalJob(query.state.data?.status) ? false : pollMs),
    staleTime: 0,
  });

/** The job, polled. When it turns terminal the tender's documents are refreshed once, because the
 * version's processing_status (and its extraction jobs) change with it. */
export function useJob(jobId: string, tenderId: string, pollMs?: number) {
  const queryClient = useQueryClient();
  const query = useQuery(jobQueryOptions(jobId, pollMs));
  const terminal = isTerminalJob(query.data?.status);
  useEffect(() => {
    if (terminal) void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] });
  }, [terminal, tenderId, queryClient]);
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
