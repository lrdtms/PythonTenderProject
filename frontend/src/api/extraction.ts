import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { isTerminalJob } from "@/lib/status-text";

import { get, post } from "./client";
import { shouldPoll } from "./jobs";
import type { ExtractionStatus, Job } from "./types";

export const EXTRACTION_POLL_MS = 3000;

export const anyJobActive = (status?: ExtractionStatus): boolean =>
  !!status?.kinds.some((k) => k.job && !isTerminalJob(k.job.status));

export const extractionQueryOptions = (versionId: string, pollMs = EXTRACTION_POLL_MS) =>
  queryOptions({
    queryKey: ["extraction", versionId] as const,
    queryFn: ({ signal }) => get<ExtractionStatus>(`/api/v1/document-versions/${versionId}/extraction`, undefined, signal),
    // Poll while any job is active; stops on 4xx and after repeated failures like every polled query.
    refetchInterval: (query) => shouldPoll(query, pollMs, (data) => !anyJobActive(data)),
    staleTime: 0,
  });

export function useRequestExtraction(versionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deepScan: boolean) =>
      post<Job[]>(`/api/v1/document-versions/${versionId}/extract`, { deep_scan: deepScan }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["extraction", versionId] }),
  });
}

/** Cancel a queued or running extraction job by id. The variables are the job id. */
export function useCancelJob(versionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => post<Job>(`/api/v1/jobs/${jobId}/cancel`),
    onSettled: (_data, _error, jobId) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["extraction", versionId] }),
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
      ]),
  });
}
