import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, post } from "./client";
import type { Tender, TenderCreate } from "./types";

export const tendersQueryOptions = (includeArchived = false) =>
  queryOptions({
    queryKey: ["tenders", { includeArchived }] as const,
    queryFn: ({ signal }) => get<Tender[]>("/api/v1/tenders", { include_archived: includeArchived }, signal),
  });

export const tenderQueryOptions = (id: string) =>
  queryOptions({
    queryKey: ["tender", id] as const,
    queryFn: ({ signal }) => get<Tender>(`/api/v1/tenders/${id}`, undefined, signal),
  });

export function useCreateTender() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TenderCreate) => post<Tender>("/api/v1/tenders", input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenders"] }),
  });
}

export function useArchiveTender() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<Tender>(`/api/v1/tenders/${id}/archive`),
    onSuccess: (_tender, id) => {
      void queryClient.invalidateQueries({ queryKey: ["tenders"] });
      void queryClient.invalidateQueries({ queryKey: ["tender", id] });
    },
  });
}
