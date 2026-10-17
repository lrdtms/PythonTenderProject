import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

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

/** Merge `id` into `intoId`: the source supplier is removed. */
export function useMergeSupplier() {
  const refresh = useRefreshSuppliers();
  return useMutation({
    mutationFn: ({ id, intoId }: { id: string; intoId: string }) =>
      post<Supplier>(`/api/v1/suppliers/${id}/merge`, { into_id: intoId }),
    onSuccess: refresh,
  });
}
