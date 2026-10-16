"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { tendersQueryOptions, useArchiveTender, useCreateTender } from "@/api/tenders";
import type { Tender, TenderCreate } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { Field } from "@/components/field";
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
    <form onSubmit={submit} className="mb-8 grid gap-4 rounded border border-zinc-300 p-4 sm:grid-cols-2 dark:border-zinc-700">
      <h2 className="text-lg font-medium sm:col-span-2">New tender</h2>
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
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {create.isPending ? "Creating…" : "Create tender"}
        </button>
      </div>
    </form>
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
          className="rounded border border-red-600 px-3 py-1 text-sm text-red-700 disabled:opacity-50 dark:text-red-300"
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
        className="rounded border border-zinc-300 px-3 py-1 text-sm dark:border-zinc-700"
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
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Tenders</h1>
      {canEdit ? <CreateForm /> : null}
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
        Show archived
      </label>
      {isPending ? <p role="status" className="text-sm text-zinc-500">Loading tenders…</p> : null}
      {error && !data ? (
        <div role="alert">
          <p className="mb-2">{messageOf(error, "Could not load tenders.")}</p>
          <button type="button" onClick={() => refetch()} className="rounded border px-3 py-1 text-sm">
            Try again
          </button>
        </div>
      ) : null}
      {error && data ? <StaleNote message="Could not refresh the list." onCheckAgain={() => void refetch()} /> : null}
      {data && data.length === 0 ? <p className="text-zinc-600 dark:text-zinc-400">No tenders yet.</p> : null}
      {data && data.length > 0 ? (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {data.map((tender) => (
            <li key={tender.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div>
                <Link href={`/tenders/${tender.id}`} className="font-medium underline">
                  {tender.title}
                </Link>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {[tender.reference_number, tender.client_name, tender.location].filter(Boolean).join(" · ")}
                  {tender.closing_at ? ` · closes ${formatDateTime(tender.closing_at)}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge tone={tenderTone(tender.status)} label={tenderStatusLabel(tender.status)} />
                {canEdit && tender.status !== "archived" ? <ArchiveControl tender={tender} /> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
