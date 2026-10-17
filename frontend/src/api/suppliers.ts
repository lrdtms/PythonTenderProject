import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";
import { get, patch, post } from "./client";
import type { Supplier, SupplierCreate, SupplierPatch } from "./types";

export const suppliersQueryOptions = queryOptions({
  queryKey: ["suppliers"] as const,
  queryFn: ({ signal }) => get<Supplier[]>("/api/v1/suppliers", undefined, signal),
});

function useRefreshSuppliers() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["suppliers"] });
    void client.invalidateQueries({ queryKey: ["quotations"] });
    void client.invalidateQueries({ queryKey: ["matches"] });
  };
}

export function useCreateSupplier() {
  const refresh = useRefreshSuppliers();
  return useMutation({
    mutationFn: (input: SupplierCreate) => post<Supplier>("/api/v1/suppliers", input),
    onSuccess: refresh,
  });
}

export function useUpdateSupplier() {
  const refresh = useRefreshSuppliers();
  return useMutation({
    mutationFn: ({ id, patch: body }: { id: string; patch: SupplierPatch }) =>
      patch<Supplier>(`/api/v1/suppliers/${id}`, body),
    onSuccess: refresh,
  });
}

export type MergeInput = { id: string; intoId: string; name: string; intoName: string };

/** Merge `id` into `intoId`: the source supplier is removed. `onMerged` runs from the hook, not the call
 * site, because the source row unmounts when the list refreshes and per-call callbacks would be skipped. */
export function useMergeSupplier(onMerged?: (input: MergeInput) => void) {
  const refresh = useRefreshSuppliers();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, intoId }: MergeInput) => post<Supplier>(`/api/v1/suppliers/${id}/merge`, { into_id: intoId }),
    onSuccess: (_data, input) => {
      refresh();
      onMerged?.(input);
    },
    onError: (error) => {
      // The list is stale when a supplier vanished or changed under us: reload it.
      const known = ["match_conflict", "tender_archived", "supplier_exists"];
      if (error instanceof ApiError && (error.isNotFound || error.code === "try_again" || (error.isConflict && !known.includes(error.code)))) {
        void client.invalidateQueries({ queryKey: ["suppliers"] });
      }
    },
  });
}
