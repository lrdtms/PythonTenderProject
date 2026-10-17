import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, patch } from "./client";
import type { Quotation, QuotationPatch } from "./types";

export const quotationsQueryOptions = (tenderId: string) =>
  queryOptions({
    queryKey: ["quotations", tenderId] as const,
    queryFn: ({ signal }) => get<Quotation[]>(`/api/v1/tenders/${tenderId}/quotations`, undefined, signal),
  });

export function useUpdateQuotation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch: body }: { id: string; patch: QuotationPatch }) =>
      patch<Quotation>(`/api/v1/quotations/${id}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["quotations"] });
      void client.invalidateQueries({ queryKey: ["matches"] });
      void client.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });
}
