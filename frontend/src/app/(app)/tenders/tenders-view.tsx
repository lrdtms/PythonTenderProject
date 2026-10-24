"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { tendersQueryOptions, useArchiveTender, useCreateTender } from "@/api/tenders";
import type { Tender, TenderCreate } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { Field } from "@/components/field";
import { SkeletonRows } from "@/components/skeleton-rows";
import { StaleNote } from "@/components/stale-note";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { tenderStatusLabel, tenderTone } from "@/lib/status-text";

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function CreateForm() {
  const create = useCreateTender();
  const [title, setTitle] = useState("");
  const [reference, setReference] = useState("");
  const [client, setClient] = useState("");
  const [location, setLocation] = useState("");
  const [closing, setClosing] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending) return;
    const input: TenderCreate = { title: title.trim() };
    if (reference.trim()) input.reference_number = reference.trim();
    if (client.trim()) input.client_name = client.trim();
    if (location.trim()) input.location = location.trim();
    if (closing) input.closing_at = new Date(closing).toISOString();
    create.mutate(input, {
      onSuccess: () => {
        setTitle("");
        setReference("");
        setClient("");
        setLocation("");
        setClosing("");
      },
    });
  }

  return (
    <details className="group mb-6">
      <summary className="btn btn-primary w-fit list-none group-open:mb-4 [&::-webkit-details-marker]:hidden">New tender</summary>
    <form onSubmit={submit} className="panel grid gap-4 p-4 sm:grid-cols-2">
      <Field label="Title" required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
      <Field label="Reference number" maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} />
      <Field label="Client" maxLength={200} value={client} onChange={(e) => setClient(e.target.value)} />
      <Field label="Location" maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} />
      <Field label="Closing date" type="datetime-local" value={closing} onChange={(e) => setClosing(e.target.value)} />
      {create.error ? (
        <p role="alert" className="text-sm text-red-600 sm:col-span-2">
          {messageOf(create.error, "Could not create the tender.")}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <button
          type="submit"
          disabled={create.isPending || !title.trim()}
          className="btn btn-primary"
        >
          {create.isPending ? "Creating…" : "Create tender"}
        </button>
      </div>
    </form>
    </details>
  );
}

function ArchiveControl({ tender }: { tender: Tender }) {
  const archive = useArchiveTender();
  const [confirming, setConfirming] = useState(false);
  if (confirming) {
    return (
      <span className="flex items-center gap-2">
        <button
          type="button"
          disabled={archive.isPending}
          onClick={() => archive.mutate(tender.id, { onSettled: () => setConfirming(false) })}
          aria-label={`Confirm archive of ${tender.title}`}
          className="btn btn-danger btn-sm"
        >
          Confirm archive
        </button>
        <button
          type="button"
          disabled={archive.isPending}
          onClick={() => setConfirming(false)}
          aria-label={`Cancel archiving ${tender.title}`}
          className="text-sm underline"
        >
          Cancel
        </button>
      </span>
    );
  }
  return (
    <span>
      <button
        type="button"
        onClick={() => setConfirming(true)}
        aria-label={`Archive ${tender.title}`}
        className="btn btn-sm"
      >
        Archive
      </button>
      {archive.error ? (
        <span role="alert" className="ml-2 text-sm text-red-600">
          {messageOf(archive.error, "Could not archive.")}
        </span>
      ) : null}
    </span>
  );
}

export function TendersView() {
  const canEdit = useCan("edit_tenders");
  const [showArchived, setShowArchived] = useState(false);
  const { data, error, isPending, refetch } = useQuery(tendersQueryOptions(showArchived));

  return (
    <section>
      <h1 className="mb-1 text-[22px] font-semibold leading-tight">Tenders</h1>
      <p className="mb-5 text-sm text-zinc-500">Each tender holds its documents, requirements, supplier quotes and estimate.</p>
      {canEdit ? <CreateForm /> : null}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-zinc-500">{data ? (data.length === 1 ? "1 tender" : `${data.length} tenders`) : " "}</p>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived
        </label>
      </div>
      {isPending ? <SkeletonRows label="Loading tenders…" rows={5} height={56} /> : null}
      {error && !data ? (
        <div role="alert">
          <p className="mb-2">{messageOf(error, "Could not load tenders.")}</p>
          <button type="button" onClick={() => refetch()} className="btn">
            Try again
          </button>
        </div>
      ) : null}
      {error && data ? <StaleNote message="Could not refresh the list." onCheckAgain={() => void refetch()} /> : null}
      {data && data.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[var(--control)] px-4 py-3 text-sm text-zinc-500">
          No tenders yet. Create the first one to start uploading its documents.
        </p>
      ) : null}
      {data && data.length > 0 ? (
        <>
          <div aria-hidden="true" className="hidden border-b border-zinc-200 px-1 pb-2 text-xs text-zinc-500 md:grid md:grid-cols-[minmax(0,1fr)_170px_130px_210px] md:gap-4">
            <span>Tender</span>
            <span className="text-right">Closes</span>
            <span>Status</span>
            <span />
          </div>
          <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {data.map((tender) => (
              <li key={tender.id} className="grid items-center gap-x-4 gap-y-1 px-1 py-3 md:grid-cols-[minmax(0,1fr)_170px_130px_210px]">
                <div className="min-w-0">
                  <Link href={`/tenders/${tender.id}`} className="block truncate font-medium hover:underline">
                    {tender.title}
                  </Link>
                  <p className="truncate text-sm text-zinc-500">
                    {[tender.reference_number, tender.client_name, tender.location].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <p className="num text-sm text-zinc-500 md:text-right">
                  {tender.closing_at ? <><span className="md:hidden">Closes </span>{formatDateTime(tender.closing_at)}</> : <span aria-label="No closing date">—</span>}
                </p>
                <div>
                  <StatusBadge tone={tenderTone(tender.status)} label={tenderStatusLabel(tender.status)} />
                </div>
                <div className="md:text-right">
                  {canEdit && tender.status !== "archived" ? <ArchiveControl tender={tender} /> : null}
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
