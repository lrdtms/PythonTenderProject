"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { documentsQueryOptions } from "@/api/documents";
import { ApiError } from "@/api/errors";
import { tenderQueryOptions } from "@/api/tenders";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { tenderStatusLabel, tenderTone } from "@/lib/status-text";

import { DocumentCard } from "./document-card";

export function TenderWorkspace() {
  const { id } = useParams<{ id: string }>();
  const tender = useQuery(tenderQueryOptions(id));
  const documents = useQuery(documentsQueryOptions(id));

  if (tender.isPending) return <p role="status" className="text-sm text-zinc-500">Loading tender…</p>;
  if (!tender.data) {
    const notFound = tender.error instanceof ApiError && tender.error.isNotFound;
    return (
      <div role="alert">
        <p className="mb-2">
          {notFound ? "This tender was not found." : tender.error instanceof ApiError ? tender.error.message : "Could not load the tender."}
        </p>
        <Link href="/tenders" className="underline">
          Back to tenders
        </Link>
      </div>
    );
  }
  const t = tender.data;
  const archived = t.status === "archived";

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link href="/tenders" className="underline">
          ← Tenders
        </Link>
      </p>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t.title}</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {[t.reference_number, t.client_name, t.location].filter(Boolean).join(" · ")}
            {t.closing_at ? ` · closes ${formatDateTime(t.closing_at)}` : ""}
          </p>
        </div>
        <StatusBadge tone={tenderTone(t.status)} label={tenderStatusLabel(t.status)} />
      </header>
      {archived ? (
        <p className="mb-4 rounded border border-zinc-400 p-3 text-sm">This tender is archived and read-only.</p>
      ) : null}

      <h2 className="mb-2 text-lg font-medium">Documents</h2>
      {documents.isPending ? <p role="status" className="text-sm text-zinc-500">Loading documents…</p> : null}
      {documents.error && !documents.data ? (
        <p role="alert" className="text-sm text-red-600">
          {documents.error instanceof ApiError ? documents.error.message : "Could not load the documents."}
        </p>
      ) : null}
      {documents.data && documents.data.length === 0 ? (
        <p className="text-zinc-600 dark:text-zinc-400">No documents yet.</p>
      ) : null}
      {documents.data && documents.data.length > 0 ? (
        <ul aria-label="Documents" className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {documents.data.map((d) => (
            <DocumentCard key={d.id} document={d} tenderId={id} archived={archived} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
