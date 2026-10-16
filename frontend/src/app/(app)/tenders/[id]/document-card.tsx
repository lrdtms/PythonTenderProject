"use client";

import type { DocumentItem } from "@/api/types";
import { JobProgress } from "@/components/job-progress";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { documentKindLabel, processingStatusLabel, processingTone } from "@/lib/status-text";

type Props = { document: DocumentItem; tenderId: string; archived: boolean };

export function DocumentCard({ document, tenderId }: Props) {
  const version = document.current_version;
  return (
    <li className="space-y-3 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium">{document.title}</p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            <span>{documentKindLabel(document.kind)}</span>
            {version ? ` · version ${version.version_number} · ${version.filename}` : ""}
            {` · added ${formatDateTime(document.created_at)}`}
          </p>
        </div>
        {version ? (
          <StatusBadge tone={processingTone(version.processing_status)} label={processingStatusLabel(version.processing_status)} />
        ) : null}
      </div>
      {version?.job_id ? <JobProgress jobId={version.job_id} tenderId={tenderId} /> : null}
    </li>
  );
}
