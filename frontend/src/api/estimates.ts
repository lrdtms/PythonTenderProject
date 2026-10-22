import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";
import { api, get, patch, post } from "./client";
import type { components } from "./schema";

export const ESTIMATE_LINE_PAGE_SIZE = 100;

type Schemas = components["schemas"];
export type Estimate = Schemas["EstimateDTO"];
export type EstimateSummary = Schemas["EstimateSummaryDTO"];
export type EstimateLine = Schemas["EstimateLineDTO"];
export type EstimatePatch = Schemas["EstimatePatch"];
export type LinePut = Schemas["LinePut"];
export type PricingDefaults = Schemas["PricingDefaultsDTO"];
export type PricingDefaultsPut = Schemas["PricingDefaultsPut"];

export type Blocker = {
  line_id: string | null;
  code: "unresolved" | "source_changed" | "unreviewed_source" | "no_lines";
};

const BLOCKER_CODES = ["unresolved", "source_changed", "unreviewed_source", "no_lines"];

/** The blockers of an `estimate_not_ready` error, or [] when the error carries none (or malformed ones). */
export function notReadyBlockers(error: unknown): Blocker[] {
  if (!(error instanceof ApiError)) return [];
  const details = error.details as { blockers?: unknown } | null | undefined;
  const list = details?.blockers;
  if (!Array.isArray(list)) return [];
  const out: Blocker[] = [];
  for (const b of list) {
    if (typeof b !== "object" || b === null) return [];
    const { line_id, code } = b as { line_id?: unknown; code?: unknown };
    if (typeof code !== "string" || !BLOCKER_CODES.includes(code)) return [];
    if (line_id !== null && typeof line_id !== "string") return [];
    out.push({ line_id, code } as Blocker);
  }
  return out;
}

export type EstimateLineFilters = {
  status?: EstimateLine["status"];
};

export function usePricingDefaults() {
  return useQuery({
    queryKey: ["pricing-defaults"] as const,
    queryFn: ({ signal }) => get<PricingDefaults>("/api/v1/pricing-defaults", undefined, signal),
  });
}

/** Every estimate write changes the estimate, its lines and the tender's version list. A refused write can also
 * mean the view is stale (a frozen estimate, a changed line), so the refresh runs on settle, not only on success. */
function useEstimateRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["estimate"] });
    void client.invalidateQueries({ queryKey: ["estimate-lines"] });
    void client.invalidateQueries({ queryKey: ["estimates"] });
  };
}

export function useSavePricingDefaults() {
  const refresh = useEstimateRefresh();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: PricingDefaultsPut) => api<PricingDefaults>("/api/v1/pricing-defaults", { method: "PUT", json: input }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["pricing-defaults"] });
      refresh();
    },
  });
}

export function useEstimates(tenderId: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["estimates", tenderId] as const,
    queryFn: ({ signal }) => get<EstimateSummary[]>(`/api/v1/tenders/${tenderId}/estimates`, undefined, signal),
  });
}

export function useEstimate(id: string) {
  return useQuery({
    enabled: id !== "",
    queryKey: ["estimate", id] as const,
    queryFn: ({ signal }) => get<Estimate>(`/api/v1/estimates/${id}`, undefined, signal),
  });
}

/** Pages are counted in BoQ lines, in BoQ order. A short page is the last one. */
export function useEstimateLines(id: string, filters: EstimateLineFilters) {
  const query = useInfiniteQuery({
    queryKey: ["estimate-lines", id, filters] as const,
    queryFn: ({ pageParam, signal }) =>
      get<EstimateLine[]>(
        `/api/v1/estimates/${id}/lines`,
        { status: filters.status, limit: ESTIMATE_LINE_PAGE_SIZE, offset: pageParam },
        signal,
      ),
    initialPageParam: 0,
    getNextPageParam: (last, all) =>
      last.length < ESTIMATE_LINE_PAGE_SIZE ? undefined : all.length * ESTIMATE_LINE_PAGE_SIZE,
    staleTime: 0,
  });
  const lines: EstimateLine[] = query.data?.pages.flat() ?? [];
  return { ...query, lines };
}

export function useCreateEstimate(tenderId: string) {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: () => post<Estimate>(`/api/v1/tenders/${tenderId}/estimates`),
    onSettled: refresh,
  });
}

/** Choose a line's price: a confirmed match, a manual price, or an exclusion (see LinePut).
 * PUT replaces the whole source: an omitted labour_rate or markup_override_percent is cleared, so send the
 * current values again when only changing something else. */
export function usePriceLine() {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: ({ lineId, body }: { lineId: string; body: LinePut }) =>
      api<EstimateLine>(`/api/v1/estimate-lines/${lineId}`, { method: "PUT", json: body }),
    onSettled: refresh,
  });
}

/** Re-read a line's live inputs and clear its "source changed" state. */
export function useRefreshLine() {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: (lineId: string) => post<EstimateLine>(`/api/v1/estimate-lines/${lineId}/refresh`),
    onSettled: refresh,
  });
}

export function usePatchEstimate() {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: ({ id, patch: body }: { id: string; patch: EstimatePatch }) =>
      patch<Estimate>(`/api/v1/estimates/${id}`, body),
    onSettled: refresh,
  });
}

export function useReviewEstimate() {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: (id: string) => post<Estimate>(`/api/v1/estimates/${id}/review`),
    onSettled: refresh,
  });
}

export function useReopenEstimate() {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: (id: string) => post<Estimate>(`/api/v1/estimates/${id}/reopen`),
    onSettled: refresh,
  });
}

export function useApproveEstimate() {
  const refresh = useEstimateRefresh();
  return useMutation({
    mutationFn: (id: string) => post<Estimate>(`/api/v1/estimates/${id}/approve`),
    onSettled: refresh,
  });
}
