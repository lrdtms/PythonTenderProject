"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/api/errors";
import { anyJobActive, extractionQueryOptions, useRequestExtraction } from "@/api/extraction";
import type { KindStatus } from "@/api/types";
import { jobErrorText, jobStatusLabel, jobTone, kindLabel, warningText } from "@/lib/status-text";

import { useCan } from "./auth-gate";
import { StaleNote } from "./stale-note";
import { StatusBadge } from "./status-badge";

const REFUSALS: Record<string, string> = {
  extraction_options_conflict: "An extraction with different options is already running. Wait for it to finish.",
  tender_archived: "This tender is archived, so nothing can be extracted.",
  not_processed: "The document has not finished processing yet.",
};

function countText(kind: string, counts: Record<string, unknown>): string | null {
  const n = (key: string) => (typeof counts[key] === "number" ? (counts[key] as number) : null);
  if (kind === "boq") {
    const items = n("items");
    return items === null ? null : `${items} ${items === 1 ? "line" : "lines"}`;
  }
  const count = n("requirements");
  return count === null ? null : `${count} ${count === 1 ? "requirement" : "requirements"}`;
}

function KindRow({ item }: { item: KindStatus }) {
  const job = item.job;
  const counts = item.run?.counts ? countText(item.kind, item.run.counts as Record<string, unknown>) : null;
  const warnings = [...(job?.warnings ?? []), ...(item.run?.warnings ?? [])];
  const seen = new Set<string>();
  const unique = warnings.map(warningText).filter((t) => (seen.has(t) ? false : (seen.add(t), true)));
  return (
    <li className="space-y-1 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{kindLabel(item.kind)}</span>
        {job ? <StatusBadge tone={jobTone(job.status)} label={jobStatusLabel(job.status)} /> : null}
        {counts ? <span>{counts}</span> : null}
      </div>
      {job?.status === "failed" ? <p className="text-red-700 dark:text-red-300">{jobErrorText(job.error_code)}</p> : null}
      {unique.length > 0 ? (
        <ul className="list-disc pl-5 text-amber-800 dark:text-amber-300">
          {unique.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

type Props = { versionId: string; ready: boolean; archived?: boolean; pollMs?: number };

export function ExtractionPanel({ versionId, ready, archived = false, pollMs }: Props) {
  const canRun = useCan("review_data") && !archived;
  const status = useQuery({ ...extractionQueryOptions(versionId, pollMs), enabled: ready });
  const request = useRequestExtraction(versionId);
  const [deep, setDeep] = useState(false);
  if (!ready) return null;
  if (status.isPending) return <p role="status" className="text-sm text-zinc-500">Checking extraction…</p>;
  if (!status.data) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {status.error instanceof ApiError ? status.error.message : "Could not load the extraction status."}
      </p>
    );
  }
  const kinds = status.data.kinds.filter((k) => k.job || k.run);
  const busy = anyJobActive(status.data) || request.isPending;
  const refusal = request.error instanceof ApiError ? (REFUSALS[request.error.code] ?? request.error.message) : request.error ? "Could not start the extraction." : null;

  return (
    <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
      <h3 className="text-sm font-semibold">Extraction</h3>
      {status.error ? <StaleNote message="Could not refresh the status." onCheckAgain={() => void status.refetch()} /> : null}
      {kinds.length === 0 ? <p className="py-2 text-sm text-zinc-600 dark:text-zinc-400">Extraction has not run yet.</p> : null}
      {kinds.length > 0 ? (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {kinds.map((k) => (
            <KindRow key={k.kind} item={k} />
          ))}
        </ul>
      ) : null}
      {refusal ? <p role="alert" className="mt-2 text-sm text-red-600">{refusal}</p> : null}
      {canRun ? (
        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} disabled={busy} />
            Deep scan (slower, reads every section)
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => request.mutate(deep)}
            className="rounded border border-zinc-400 px-3 py-1 disabled:opacity-50"
          >
            {request.isPending ? "Starting…" : "Run extraction again"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
