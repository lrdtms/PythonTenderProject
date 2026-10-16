"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { useUploadDocument } from "@/api/uploads";
import { useCan } from "@/components/auth-gate";
import { Field } from "@/components/field";
import { ACCEPT, MAX_UPLOAD_MB, formatBytes, validateFile } from "@/lib/file-rules";

const KINDS: [string, string][] = [
  ["tender_document", "Tender document"],
  ["boq", "Bill of quantities"],
  ["quotation", "Quotation"],
  ["other", "Other"],
];

export function UploadForm({ tenderId }: { tenderId: string }) {
  const canUpload = useCan("upload_documents");
  const uploadDocument = useUploadDocument(tenderId);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("tender_document");
  const [title, setTitle] = useState("");
  const [fraction, setFraction] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const kindId = useId();
  const fileId = useId();
  const hintId = useId();
  const fileInput = useRef<HTMLInputElement>(null);

  if (!canUpload) return null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (uploadDocument.isPending) return;
    setDone(false);
    if (!file) {
      uploadDocument.reset();
      setProblem("Choose a file to upload.");
      return;
    }
    const invalid = validateFile(file);
    if (invalid) {
      uploadDocument.reset(); // only one message at a time
      setProblem(invalid);
      return;
    }
    setProblem(null);
    setFraction(0);
    uploadDocument.mutate(
      { file, kind, title: title.trim() || undefined, onProgress: setFraction },
      {
        onSuccess: () => {
          setDone(true);
          setFile(null);
          setTitle("");
          if (fileInput.current) fileInput.current.value = "";
        },
      },
    );
  }

  const shown = problem ?? (uploadDocument.error instanceof ApiError ? uploadDocument.error.message : uploadDocument.error ? "The upload failed. Try again." : null);

  return (
    <form onSubmit={submit} className="mb-8 grid gap-4 rounded border border-zinc-300 p-4 sm:grid-cols-2 dark:border-zinc-700">
      <h2 className="text-lg font-medium sm:col-span-2">Upload a document</h2>
      <div className="flex flex-col gap-1">
        <label htmlFor={kindId} className="text-sm font-medium">Document type</label>
        <select id={kindId} value={kind} onChange={(e) => setKind(e.target.value)} className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700">
          {KINDS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>
      <Field label="Title (optional)" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      <div className="flex flex-col gap-1 sm:col-span-2">
        <label htmlFor={fileId} className="text-sm font-medium">File</label>
        <input
          ref={fileInput}
          id={fileId}
          aria-describedby={hintId}
          disabled={uploadDocument.isPending}
          type="file"
          accept={ACCEPT}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            uploadDocument.reset();
            setProblem(null);
            setDone(false);
          }}
        />
        <p id={hintId} className="text-xs text-zinc-500">
          PDF, XLSX, CSV or DOCX, up to {MAX_UPLOAD_MB} MB.{file ? ` Selected: ${file.name} (${formatBytes(file.size)}).` : ""}
        </p>
      </div>
      {uploadDocument.isPending ? (
        <progress aria-label="Upload progress" className="sm:col-span-2" value={fraction} max={1} />
      ) : null}
      {shown ? <p role="alert" className="text-sm text-red-600 sm:col-span-2">{shown}</p> : null}
      {done ? <p role="status" className="text-sm text-green-700 sm:col-span-2 dark:text-green-300">Uploaded. Processing has started.</p> : null}
      <div className="sm:col-span-2">
        <button type="submit" disabled={uploadDocument.isPending} className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
          {uploadDocument.isPending ? "Uploading…" : "Upload"}
        </button>
      </div>
    </form>
  );
}
