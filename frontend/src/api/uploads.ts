import { useMutation, useQueryClient } from "@tanstack/react-query";

import { upload } from "./client";
import type { UploadResult } from "./types";

type UploadInput = { file: File; kind?: string; title?: string; onProgress?: (fraction: number) => void };

// Uploads are deliberately NOT aborted on unmount: the user most likely wants them to finish, and the
// hook still refreshes the documents on success. A cancel feature would pass an AbortSignal to `upload`.
function useUpload(path: string, tenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, kind, title, onProgress }: UploadInput) => {
      const fields: Record<string, string> = {};
      if (kind) fields.kind = kind;
      if (title) fields.title = title;
      return upload<UploadResult>(path, file, fields, onProgress);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", tenderId] }),
  });
}

export const useUploadDocument = (tenderId: string) => useUpload(`/api/v1/tenders/${tenderId}/documents`, tenderId);
export const useUploadVersion = (tenderId: string, documentId: string) =>
  useUpload(`/api/v1/documents/${documentId}/versions`, tenderId);
