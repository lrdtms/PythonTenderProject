import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { get } from "./client";
import type { components } from "./schema";

export type AuditEvent = components["schemas"]["AuditEventRow"];
type AuditPage = components["schemas"]["AuditRows"];
export type AuditFacets = components["schemas"]["AuditFacets"];

export type AuditFilters = {
  entityType?: string;
  action?: string;
  userId?: string;
  from?: string;
  to?: string;
};

export const AUDIT_PAGE_SIZE = 50;

/** Newest first, paged by the server's opaque cursor. A filter change changes the key, so the
 * list restarts from the first page. */
export function useAuditEvents(filters: AuditFilters, enabled = true) {
  const query = useInfiniteQuery({
    queryKey: [
      "audit",
      filters.entityType ?? null,
      filters.action ?? null,
      filters.userId ?? null,
      filters.from ?? null,
      filters.to ?? null,
    ] as const,
    queryFn: ({ pageParam, signal }) =>
      get<AuditPage>(
        "/api/v1/audit",
        {
          limit: AUDIT_PAGE_SIZE,
          cursor: pageParam,
          entity_type: filters.entityType,
          action: filters.action,
          user_id: filters.userId,
          from: filters.from,
          to: filters.to,
        },
        signal,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled,
    staleTime: 0,
  });
  const rows: AuditEvent[] = query.data?.pages.flatMap((p) => p.items) ?? [];
  return { ...query, rows };
}

export function useAuditFacets(enabled = true) {
  return useQuery({
    queryKey: ["audit", "facets"] as const,
    queryFn: ({ signal }) => get<AuditFacets>("/api/v1/audit/facets", undefined, signal),
    enabled,
    staleTime: 30_000,
  });
}
