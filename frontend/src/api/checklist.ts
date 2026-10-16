import { useInfiniteQuery } from "@tanstack/react-query";

import { get } from "./client";
import { REVIEW_PAGE_SIZE } from "./review";
import type { Requirement } from "./types";

export type ChecklistFilters = { reviewStatus?: string; requirementType?: string };

/** Requirements of every document's current version in the tender, paged by offset. Changing a
 * filter changes the query key, so the list restarts from offset 0. */
export function useTenderRequirements(tenderId: string, filters: ChecklistFilters, enabled = true) {
  const query = useInfiniteQuery({
    queryKey: ["checklist", tenderId, filters.reviewStatus ?? null, filters.requirementType ?? null] as const,
    queryFn: ({ pageParam, signal }) =>
      get<Requirement[]>(
        `/api/v1/tenders/${tenderId}/requirements`,
        {
          limit: REVIEW_PAGE_SIZE,
          offset: pageParam,
          review_status: filters.reviewStatus,
          requirement_type: filters.requirementType,
        },
        signal,
      ),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length < REVIEW_PAGE_SIZE ? undefined : all.length * REVIEW_PAGE_SIZE),
    enabled,
    staleTime: 0,
  });
  const rows: Requirement[] = query.data?.pages.flat() ?? [];
  return { ...query, rows };
}
