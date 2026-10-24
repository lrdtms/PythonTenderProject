"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef } from "react";

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
  const noteId = useId();

  if (!allowed) return null;

  const run = () => {
    if (busy.current) return;
    busy.current = true;
    create.mutate(
      { kind, estimateId },
      {
        onSuccess: (file) => {
          startDownload(file);
          if (kind === "checklist_pdf") {
            void client.invalidateQueries({ queryKey: ["checklist", tenderId, "unreviewed"] });
          } else {
            void client.invalidateQueries({ queryKey: ["estimates"] });
            void client.invalidateQueries({ queryKey: ["estimate"] });
          }
        },
        onSettled: () => {
          busy.current = false;
        },
      },
    );
  };

  const done = create.isSuccess ? create.data : null;
  const showNote = !!draftNote && !done;

  return (
    <div className="flex flex-col gap-1">
      {showNote && (
        <p id={noteId} className="text-sm font-medium text-amber-800 dark:text-amber-300">
          {draftNote}
        </p>
      )}
      <div>
        <button
          type="button"
          className="btn"
          disabled={create.isPending}
          aria-describedby={showNote ? noteId : undefined}
          onClick={run}
        >
          {create.isPending ? "Preparing file" : label}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {exportErrorText(create.error)}
        </p>
      )}
      <p role="status" aria-live="polite" className="text-sm text-[var(--ink)]">
        {done && (
          <>
            Downloaded{" "}
            <a className="underline" href={exportDownloadPath(done.id)} download={done.file_name}>
              {done.file_name}
            </a>
            {done.label !== "approved" && " (marked DRAFT)"}
          </>
        )}
      </p>
    </div>
  );
}
