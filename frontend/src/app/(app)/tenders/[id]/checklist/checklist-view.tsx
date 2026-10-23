"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { useTenderRequirements } from "@/api/checklist";
import { documentsQueryOptions } from "@/api/documents";
import { ApiError } from "@/api/errors";
import { tenderQueryOptions } from "@/api/tenders";
import type { Requirement } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { ExportButton } from "@/components/export-button";
import { StatusBadge } from "@/components/status-badge";
import {
  MANDATORY_STATUSES,
  REQUIREMENT_TYPES,
  mandatoryLabel,
  requirementTypeLabel,
  reviewStatusLabel,
  reviewTone,
} from "@/lib/review-text";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const REVIEW_STATUSES = ["unreviewed", "confirmed", "corrected", "rejected"] as const;

const SELECT = "rounded border bg-transparent p-1 text-sm";

export function ChecklistView() {
  const { id } = useParams<{ id: string }>();
  const valid = typeof id === "string" && UUID.test(id);
  const [reviewStatus, setReviewStatus] = useState("");
  const [requirementType, setRequirementType] = useState("");
  const [mandatory, setMandatory] = useState("");

  const tender = useQuery({ ...tenderQueryOptions(id), enabled: valid });
  const documents = useQuery({ ...documentsQueryOptions(id), enabled: valid && !!tender.data });
  const list = useTenderRequirements(
    id,
    { reviewStatus: reviewStatus || undefined, requirementType: requirementType || undefined },
    valid && !!tender.data,
  );

  // The DRAFT note must not depend on the filters on screen, so it has its own unfiltered query.
  const canExport = useCan("export");
  const open = useTenderRequirements(id, { reviewStatus: "unreviewed" }, valid && !!tender.data && canExport);
  const openCount = open.rows.length;
  // With nothing to list (no rows, or every row rejected) the report is DRAFT too.
  const everything = useTenderRequirements(id, {}, valid && !!tender.data && canExport);
  const nothingListed =
    everything.isSuccess && !everything.hasNextPage && everything.rows.every((r) => r.review_status === "rejected");
  let draftNote: string | undefined;
  if (open.isError) {
    draftNote = "The report may be marked DRAFT if requirements are not reviewed yet.";
  } else if (open.isSuccess && openCount > 0) {
    const count = `${openCount} ${openCount === 1 ? "requirement is" : "requirements are"}`;
    draftNote = `${open.hasNextPage ? "At least " : ""}${count} not reviewed yet. The report will list ${openCount === 1 ? "it" : "them"} separately and be marked DRAFT.`;
  } else if (open.isSuccess && nothingListed) {
    draftNote = "No reviewed requirements yet. The report will be marked DRAFT.";
  }

  // version id -> document title, so each row says where it came from.
  const titles = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of documents.data ?? []) if (d.current_version) map.set(d.current_version.id, d.title);
    return map;
  }, [documents.data]);

  const visible = mandatory ? list.rows.filter((r) => r.mandatory_status === mandatory) : list.rows;
  const groups = REQUIREMENT_TYPES.map((type) => ({ type, rows: visible.filter((r) => r.requirement_type === type) })).filter(
    (g) => g.rows.length > 0,
  );

  if (!valid || (tender.error instanceof ApiError && tender.error.isNotFound)) {
    return (
      <div role="alert">
        <p className="mb-2">This tender was not found.</p>
        <Link href="/tenders" className="underline">
          Back to tenders
        </Link>
      </div>
    );
  }
  if (tender.isPending) return <p role="status" className="text-sm text-zinc-500">Loading tender…</p>;
  if (!tender.data) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        Could not load the tender.
      </p>
    );
  }

  const noDocuments = !!documents.data && documents.data.length === 0;
  const nothingReady =
    !!documents.data &&
    documents.data.length > 0 &&
    !documents.data.some((d) => d.current_version?.processing_status === "ready" || d.current_version?.processing_status === "ready_with_warnings");
  const filtered = !!(reviewStatus || requirementType || mandatory);

  const row = (r: Requirement) => (
    <li key={r.id} className="rounded border border-zinc-300 p-3 dark:border-zinc-700">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <StatusBadge tone={reviewTone(r.review_status)} label={reviewStatusLabel(r.review_status)} />
        <StatusBadge tone="neutral" label={mandatoryLabel(r.mandatory_status)} />
        {r.evidence_status === "evidence_unverified" ? <StatusBadge tone="warning" label="Evidence unverified" /> : null}
        {r.needs_review ? <StatusBadge tone="warning" label="Needs review" /> : null}
      </div>
      <p className="text-sm">{r.description}</p>
      <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
        {titles.get(r.document_version_id) ?? "Document"}
        {r.page_number ? ` · page ${r.page_number}` : ""}
        {" · "}
        <Link
          href={`/tenders/${id}/review/${r.document_version_id}?row=${r.id}`}
          aria-label={`Open in review: ${r.description.slice(0, 60)}`}
          className="underline"
        >
          Open in review
        </Link>
      </p>
    </li>
  );

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link href={`/tenders/${id}`} className="underline">
          ← Back to the tender
        </Link>
      </p>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Checklist: {tender.data.title}</h1>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Requirements from the current version of every document. Open a requirement in review to see its source or change it.
      </p>

      <div className="mb-4">
        <ExportButton tenderId={id} kind="checklist_pdf" label="Download PDF report" draftNote={draftNote} />
      </div>

      <div className="mb-4 flex flex-wrap gap-3" role="group" aria-label="Filters">
        <label className="text-sm">
          <span className="mr-1 font-medium">Review status</span>
          <select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)} className={SELECT}>
            <option value="">All</option>
            {REVIEW_STATUSES.map((s) => (
              <option key={s} value={s}>
                {reviewStatusLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-1 font-medium">Type</span>
          <select value={requirementType} onChange={(e) => setRequirementType(e.target.value)} className={SELECT}>
            <option value="">All</option>
            {REQUIREMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {requirementTypeLabel(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-1 font-medium">Mandatory status</span>
          <select value={mandatory} onChange={(e) => setMandatory(e.target.value)} className={SELECT}>
            <option value="">All</option>
            {MANDATORY_STATUSES.map((m) => (
              <option key={m} value={m}>
                {mandatoryLabel(m)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {list.isPending ? <p role="status" className="text-sm text-zinc-500">Loading requirements…</p> : null}
      {list.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Could not load the requirements.
        </p>
      ) : null}
      {list.isSuccess && list.rows.length === 0 ? (
        <p className="text-sm">
          {noDocuments
            ? "No documents have been uploaded yet."
            : nothingReady
              ? "No document has finished processing yet."
              : filtered
                ? "No requirements match these filters."
                : "No requirements have been extracted yet."}{" "}
          <Link href={`/tenders/${id}`} className="underline">
            Go to the tender page
          </Link>
          .
        </p>
      ) : null}
      {list.isSuccess && list.rows.length > 0 && visible.length === 0 ? (
        <p className="text-sm">
          No loaded requirements match the mandatory status filter.
          {list.hasNextPage ? " Load more to check the rest." : ""}
        </p>
      ) : null}

      {groups.map((g) => (
        <section key={g.type} aria-labelledby={`group-${g.type}`} className="mb-6">
          <h2 id={`group-${g.type}`} className="mb-2 text-lg font-medium">
            {requirementTypeLabel(g.type)} ({g.rows.length}{list.hasNextPage ? "+" : ""})
          </h2>
          <ul className="space-y-2">{g.rows.map(row)}</ul>
        </section>
      ))}

      {list.hasNextPage ? (
        <div>
          {mandatory && visible.length > 0 ? (
            <p className="mb-2 text-xs text-zinc-600 dark:text-zinc-400">
              The mandatory status filter applies to loaded requirements only; load more to see the rest.
            </p>
          ) : null}
          <button
            type="button"
            disabled={list.isFetchingNextPage}
            onClick={() => void list.fetchNextPage()}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            Load more
          </button>
        </div>
      ) : null}
    </section>
  );
}
