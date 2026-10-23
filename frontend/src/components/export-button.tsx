"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { type Export, exportDownloadPath, useCreateExport } from "@/api/exports";
import { useCan } from "@/components/auth-gate";
import { exportErrorText } from "@/lib/export-words";

type Props = {
  tenderId: string;
  kind: "estimate_xlsx" | "checklist_pdf";
  estimateId?: string | null;
  label: string;
  /** Shown above the button before any click, e.g. "This file will be marked DRAFT". */
  draftNote?: string;
};

/** Starts the browser download through an anchor to the same-origin download route; no file is held in memory. */
function startDownload(file: Export) {
  const anchor = document.createElement("a");
  anchor.href = exportDownloadPath(file.id);
  anchor.download = file.file_name;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

export function ExportButton({ tenderId, kind, estimateId, label, draftNote }: Props) {
  const allowed = useCan("export");
  const client = useQueryClient();
  const create = useCreateExport(tenderId);
  const busy = useRef(false);

  if (!allowed) return null;

  const run = () => {
    if (busy.current) return;
    busy.current = true;
    create.mutate(
      { kind, estimateId },
      {
        onSuccess: (file) => {
          startDownload(file);
          void client.invalidateQueries({ queryKey: ["estimates"] });
          void client.invalidateQueries({ queryKey: ["estimate"] });
        },
        onSettled: () => {
          busy.current = false;
        },
      },
    );
  };

  const done = create.isSuccess ? create.data : null;

  return (
    <div className="flex flex-col gap-1">
      {draftNote && !done && <p className="text-sm text-gray-700">{draftNote}</p>}
      <div>
        <button
          type="button"
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          disabled={create.isPending}
          onClick={run}
        >
          {create.isPending ? "Preparing file" : label}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="text-sm text-red-700">
          {exportErrorText(create.error)}
        </p>
      )}
      {done && (
        <p role="status" className="text-sm">
          Downloaded{" "}
          <a className="underline" href={exportDownloadPath(done.id)} download={done.file_name}>
            {done.file_name}
          </a>
          {done.label !== "approved" && " (marked DRAFT)"}
        </p>
      )}
    </div>
  );
}
