"use client";

import { useRef, useState } from "react";

import { ApiError } from "@/api/errors";
import { useUploadVersion } from "@/api/uploads";
import { useCan } from "@/components/auth-gate";
import { ACCEPT, validateFile } from "@/lib/file-rules";

export function NewVersion({ tenderId, documentId }: { tenderId: string; documentId: string }) {
  const canUpload = useCan("upload_documents");
  const uploadVersion = useUploadVersion(tenderId, documentId);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  if (!canUpload) return null;

  const shown = problem ?? (uploadVersion.error instanceof ApiError ? uploadVersion.error.message : uploadVersion.error ? "The upload failed. Try again." : null);

  return (
    <div className="text-sm">
      <label className="mr-2 font-medium" htmlFor={`new-version-${documentId}`}>
        Upload new version
      </label>
      <input
        ref={fileInput}
        id={`new-version-${documentId}`}
        type="file"
        accept={ACCEPT}
        disabled={uploadVersion.isPending}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setDone(false);
          const invalid = validateFile(file);
          if (invalid) {
            setProblem(invalid);
            return;
          }
          setProblem(null);
          uploadVersion.mutate(
            { file },
            { onSuccess: () => { setDone(true); if (fileInput.current) fileInput.current.value = ""; } },
          );
        }}
      />
      {uploadVersion.isPending ? <span role="status" className="ml-2 text-zinc-500">Uploading…</span> : null}
      {shown ? <p role="alert" className="mt-1 text-red-600">{shown}</p> : null}
      {done ? <p role="status" className="mt-1 text-green-700 dark:text-green-300">Uploaded. Processing has started.</p> : null}
    </div>
  );
}
