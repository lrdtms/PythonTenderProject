import { useMutation } from "@tanstack/react-query";

import { post } from "./client";
import type { components } from "./schema";

export type Export = components["schemas"]["ExportDTO"];
type ExportCreate = components["schemas"]["ExportCreate"];

export type CreateExportInput = {
  kind: ExportCreate["kind"];
  estimateId?: string | null;
};

/** Generate a file. The download itself is a plain link to `exportDownloadPath`. */
export function useCreateExport(tenderId: string) {
  return useMutation({
    mutationFn: ({ kind, estimateId }: CreateExportInput) => {
      const body: ExportCreate = { kind };
      if (estimateId) body.estimate_id = estimateId;
      return post<Export>(`/api/v1/tenders/${tenderId}/exports`, body);
    },
  });
}

export const exportDownloadPath = (id: string): string => `/api/v1/exports/${id}/download`;
