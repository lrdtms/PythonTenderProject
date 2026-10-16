import {
  type InfiniteData,
  type QueryClient,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import { get, patch, post } from "./client";
import { ApiError } from "./errors";
import type {
  BoqItem,
  BoqPatch,
  DocumentVersion,
  PageDetail,
  PageSummary,
  Requirement,
  RequirementPatch,
  ReviewStatus,
} from "./types";

export const REVIEW_PAGE_SIZE = 200;

export type ReviewKind = "requirement" | "boq-item";
type Row = Requirement | BoqItem;
export type RowWindow = { from: number; to: number };

export const versionQueryOptions = (versionId: string) =>
  queryOptions({
    queryKey: ["version", versionId] as const,
    queryFn: ({ signal }) => get<DocumentVersion>(`/api/v1/document-versions/${versionId}`, undefined, signal),
  });

export const pagesQueryOptions = (versionId: string) =>
  queryOptions({
    queryKey: ["pages", versionId] as const,
    queryFn: ({ signal }) => get<PageSummary[]>(`/api/v1/document-versions/${versionId}/pages`, undefined, signal),
  });

export const pageDetailQueryOptions = (versionId: string, page: number, window?: RowWindow) =>
  queryOptions({
    queryKey: ["page", versionId, page, window?.from ?? null, window?.to ?? null] as const,
    queryFn: ({ signal }) =>
      get<PageDetail>(
        `/api/v1/document-versions/${versionId}/pages/${page}`,
        window ? { row_from: window.from, row_to: window.to } : undefined,
        signal,
      ),
  });

const segment = (kind: ReviewKind) => (kind === "requirement" ? "requirements" : "boq-items");
const listKey = (kind: ReviewKind, versionId: string) => ["review", segment(kind), versionId] as const;
const listPath = (kind: ReviewKind, versionId: string) => `/api/v1/document-versions/${versionId}/${segment(kind)}`;
const rowPath = (kind: ReviewKind, id: string) => `/api/v1/${segment(kind)}/${id}`;

function useList<T extends Row>(kind: ReviewKind, versionId: string, enabled: boolean) {
  const query = useInfiniteQuery({
    queryKey: listKey(kind, versionId),
    queryFn: ({ pageParam, signal }) =>
      get<T[]>(listPath(kind, versionId), { limit: REVIEW_PAGE_SIZE, offset: pageParam }, signal),
    initialPageParam: 0,
    // A short page is the last one; a full page may have more.
    getNextPageParam: (last, all) => (last.length < REVIEW_PAGE_SIZE ? undefined : all.length * REVIEW_PAGE_SIZE),
    enabled,
    staleTime: 0,
  });
  const rows: T[] = query.data?.pages.flat() ?? [];
  return { ...query, rows };
}

export const useRequirements = (versionId: string, enabled = true) => useList<Requirement>("requirement", versionId, enabled);
export const useBoqItems = (versionId: string, enabled = true) => useList<BoqItem>("boq-item", versionId, enabled);

function mapRows(client: QueryClient, key: readonly unknown[], fn: (row: Row) => Row) {
  client.setQueryData<InfiniteData<Row[]>>(key, (old) =>
    old ? { ...old, pages: old.pages.map((page) => page.map(fn)) } : old,
  );
}

function isReplaced(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.isRowReplaced);
}

export type ReviewVars =
  | { action: "confirm" | "reject"; id: string }
  | { action: "correct"; id: string; patch: BoqPatch | RequirementPatch };

/** One mutation for confirm, reject and correct. The cached list is updated at once and restored on
 * failure; a row that a re-run replaced resets the list so it reloads from offset 0. */
export function useReviewMutation(kind: ReviewKind, versionId: string) {
  const client = useQueryClient();
  const key = listKey(kind, versionId);
  return useMutation({
    mutationFn: (vars: ReviewVars) =>
      vars.action === "correct"
        ? patch<Row>(rowPath(kind, vars.id), vars.patch)
        : post<Row>(`${rowPath(kind, vars.id)}/${vars.action}`),
    onMutate: async (vars) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<InfiniteData<Row[]>>(key);
      const status: ReviewStatus =
        vars.action === "confirm" ? "confirmed" : vars.action === "reject" ? "rejected" : "corrected";
      mapRows(client, key, (row) => (row.id === vars.id ? { ...row, review_status: status } : row));
      return { previous };
    },
    onSuccess: (saved, vars) => {
      mapRows(client, key, (row) => (row.id === vars.id ? saved : row));
    },
    onError: (error, _vars, context) => {
      if (isReplaced(error)) {
        void client.resetQueries({ queryKey: key });
      } else if (context?.previous) {
        client.setQueryData(key, context.previous);
      }
    },
  });
}
