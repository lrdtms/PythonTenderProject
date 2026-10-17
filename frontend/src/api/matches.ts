import { type InfiniteData, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, post } from "./client";
import type { ConfirmClearResult, Job, MatchLine, MatchSuggestion } from "./types";

export const MATCH_PAGE_SIZE = 100;

export type MatchFilters = {
  status?: string;
  classification?: string;
  supplierId?: string;
  onlyWithSuggestions?: boolean;
};

type Pages = InfiniteData<MatchLine[]>;

/** Pages are counted in BoQ lines (not suggestions). A short page is the last one. */
export function useMatchLines(tenderId: string, filters: MatchFilters) {
  const query = useInfiniteQuery({
    queryKey: ["matches", tenderId, filters] as const,
    queryFn: ({ pageParam, signal }) =>
      get<MatchLine[]>(
        `/api/v1/tenders/${tenderId}/match-suggestions`,
        {
          status: filters.status,
          classification: filters.classification,
          supplier_id: filters.supplierId,
          only_with_suggestions: filters.onlyWithSuggestions,
          limit: MATCH_PAGE_SIZE,
          offset: pageParam,
        },
        signal,
      ),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length < MATCH_PAGE_SIZE ? undefined : all.length * MATCH_PAGE_SIZE),
    staleTime: 0,
  });
  const lines: MatchLine[] = query.data?.pages.flat() ?? [];
  return { ...query, lines };
}

type Decision = "confirm" | "reject" | "reset";

/** Confirm, reject and reset. The cached suggestion is replaced by the server's answer on success;
 * nothing is changed optimistically, so a refused decision (409) leaves the list as it was. */
export function useDecideMatch(tenderId: string) {
  const client = useQueryClient();
  const make = (action: Decision) => ({
    mutationFn: (id: string) => post<MatchSuggestion>(`/api/v1/match-suggestions/${id}/${action}`),
    onSuccess: (saved: MatchSuggestion) => {
      client.setQueriesData<Pages>({ queryKey: ["matches", tenderId] }, (old) =>
        old
          ? {
              ...old,
              pages: old.pages.map((page) =>
                page.map((line) => ({
                  ...line,
                  suggestions: line.suggestions.map((s) => (s.id === saved.id ? saved : s)),
                })),
              ),
            }
          : old,
      );
    },
  });
  const confirm = useMutation(make("confirm"));
  const reject = useMutation(make("reject"));
  const reset = useMutation(make("reset"));
  return { confirm, reject, reset };
}

/** Confirm every clear, unambiguous suggestion that is still open. */
export function useConfirmClear(tenderId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => post<ConfirmClearResult>(`/api/v1/tenders/${tenderId}/match-suggestions/confirm-clear`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["matches", tenderId] }),
  });
}

/** Starts a matching job (202). The page's Refresh button re-reads the lines once it finishes. */
export function useRunMatching(tenderId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => post<Job>(`/api/v1/tenders/${tenderId}/match`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["matches", tenderId] }),
  });
}
