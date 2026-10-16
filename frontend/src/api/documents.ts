import { queryOptions } from "@tanstack/react-query";

import { get } from "./client";
import type { DocumentItem } from "./types";

export const documentsQueryOptions = (tenderId: string) =>
  queryOptions({
    queryKey: ["documents", tenderId] as const,
    queryFn: ({ signal }) => get<DocumentItem[]>(`/api/v1/tenders/${tenderId}/documents`, undefined, signal),
  });
