"use client";

import { useId, useState } from "react";

import { ApiError } from "@/api/errors";
import { useUploadVersion } from "@/api/uploads";
import { useCan } from "@/components/auth-gate";
import { ACCEPT, validateFile } from "@/lib/file-rules";

export function NewVersion({ tenderId, documentId }: { tenderId: string; documentId: string }) {
  const canUpload = useCan("upload_documents");
  const uploadVersion = useUploadVersion(tenderId, documentId);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const inputId = useId();
  const [fraction, setFraction] = useState(0);
  if (!canUpload) return null;

  const shown = problem ?? (uploadVersion.error instanceof ApiError ? uploadVersion.error.message : uploadVersion.error ? "The upload failed. Try again." : null);

  return (
    <div className="text-sm">
      <label className="mr-2 text-zinc-500" htmlFor={inputId}>
        Upload new version
      </label>
      <input
        id={inputId}
        type="file"
        accept={ACCEPT}
        disabled={uploadVersion.isPending}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          // Clear the input so the same file can be chosen again after a failure.
          e.target.value = "";
          uploadVersion.reset();
          setDone(false);
          const invalid = validateFile(file);
          if (invalid) {
            setProblem(invalid);
            return;
          }
          setProblem(null);
          setFraction(0);
          uploadVersion.mutate({ file, onProgress: setFraction }, { onSuccess: () => setDone(true) });
        }}
      />
      {uploadVersion.isPending ? (
        <>
          <progress aria-label="Upload progress" className="ml-2 align-middle" value={fraction} max={1} />
          <span role="status" className="ml-2 text-zinc-500">Uploading…</span>
        </>
      ) : null}
      {shown ? <p role="alert" className="mt-1 text-red-600">{shown}</p> : null}
      {done && !uploadVersion.isPending ? <p role="status" className="mt-1 text-green-700 dark:text-green-300">Uploaded. Processing has started.</p> : null}
    </div>
  );
}
