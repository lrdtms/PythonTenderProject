"use client";

import Link from "next/link";

import type { DocumentItem } from "@/api/types";
import { ExtractionPanel } from "@/components/extraction-panel";
import { JobProgress } from "@/components/job-progress";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { documentKindLabel, processingStatusLabel, processingTone } from "@/lib/status-text";

import { NewVersion } from "./new-version";

type Props = { document: DocumentItem; tenderId: string; archived: boolean };

export function DocumentCard({ document, tenderId, archived }: Props) {
  const version = document.current_version;
  const ready = version && (version.processing_status === "ready" || version.processing_status === "ready_with_warnings");
  return (
    <li className="space-y-3 py-4">
      <div className="grid items-center gap-x-4 gap-y-2 md:grid-cols-[minmax(0,1fr)_auto_auto]">
        <div className="min-w-0">
          <p className="truncate font-medium">{document.title}</p>
          <p className="truncate text-sm text-zinc-500">
            <span>{documentKindLabel(document.kind)}</span>
            {version ? ` · version ${version.version_number} · ${version.filename}` : ""}
            {` · added ${formatDateTime(document.created_at)}`}
          </p>
        </div>
        <div>
          {version ? (
            <StatusBadge tone={processingTone(version.processing_status)} label={processingStatusLabel(version.processing_status)} />
          ) : null}
        </div>
        <div>
          {ready ? (
            <Link href={`/tenders/${tenderId}/review/${version.id}`} className="btn btn-sm">
              {document.kind === "quotation" ? "Review quotation" : "Review extracted data"}
            </Link>
          ) : null}
        </div>
      </div>
      {version?.job_id ? <JobProgress key={version.job_id} jobId={version.job_id} tenderId={tenderId} archived={archived} versionStatus={version.processing_status} /> : null}
      {!archived && version ? <NewVersion tenderId={tenderId} documentId={document.id} /> : null}
      {version ? (
        <ExtractionPanel
          key={version.id}
          versionId={version.id}
          ready={version.processing_status === "ready" || version.processing_status === "ready_with_warnings"}
          archived={archived}
        />
      ) : null}
    </li>
  );
}
