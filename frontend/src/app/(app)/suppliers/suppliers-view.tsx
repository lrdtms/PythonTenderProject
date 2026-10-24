"use client";

import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import {
  suppliersQueryOptions,
  useCreateSupplier,
  useMergeSupplier,
  useUpdateSupplier,
} from "@/api/suppliers";
import type { Supplier, SupplierPatch } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { Field } from "@/components/field";
import { supplierErrorText } from "@/lib/supplier-text";

const BUTTON = "rounded border px-2 py-1 text-sm disabled:opacity-50";
const BLANK_NAME = "Enter a name. It cannot be only spaces.";
const countText = (n: number) => `${n} ${n === 1 ? "quotation" : "quotations"}`;

function CreateSupplier({ onStart }: { onStart: () => void }) {
  const create = useCreateSupplier();
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [blank, setBlank] = useState(false);

  // Editing a field clears the previous error, so a stale message never sits beside new input.
  const touch = () => {
    if (create.isError) create.reset();
    setBlank(false);
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending) return;
    if (name.trim() === "") {
      setBlank(true);
      return;
    }
    onStart();
    const trimmedNotes = notes.trim();
    create.mutate(
      { name: name.trim(), ...(trimmedNotes ? { notes: trimmedNotes } : {}) },
      {
        onSuccess: () => {
          setName("");
          setNotes("");
        },
      },
    );
  }

  return (
    <details className="group mb-6">
      <summary className="btn btn-primary w-fit list-none group-open:mb-4 [&::-webkit-details-marker]:hidden">Add a supplier</summary>
    <form onSubmit={submit} className="panel space-y-3 p-4" aria-label="Add a supplier">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" required maxLength={200} value={name} onChange={(e) => (touch(), setName(e.target.value))} />
        <Field label="Notes" value={notes} onChange={(e) => (touch(), setNotes(e.target.value))} />
      </div>
      {blank ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {BLANK_NAME}
        </p>
      ) : null}
      {create.error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {supplierErrorText(create.error)}
        </p>
      ) : null}
      <button type="submit" disabled={create.isPending} className="btn">
        {create.isPending ? "Adding…" : "Add supplier"}
      </button>
    </form>
    </details>
  );
}

function SupplierRow({
  supplier,
  others,
  canEdit,
  onMerged,
  onStart,
}: {
  supplier: Supplier;
  others: Supplier[];
  canEdit: boolean;
  onMerged: (message: string) => void;
  onStart: () => void;
}) {
  const update = useUpdateSupplier();
  const merge = useMergeSupplier((v) => onMerged(`Merged ${v.name} into ${v.intoName}.`));
  const mergeSent = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(supplier.name);
  const [notes, setNotes] = useState(supplier.notes ?? "");
  const [targetId, setTargetId] = useState("");
  const [confirming, setConfirming] = useState(false);
  const editRef = useRef<HTMLButtonElement>(null);
  const mergeRef = useRef<HTMLButtonElement>(null);
  const busy = update.isPending || merge.isPending;
  const target = others.find((o) => o.id === targetId);
  // The chosen supplier may disappear (merged or removed elsewhere): forget the stale choice.
  if (targetId && !target) setTargetId("");
  if (confirming && !target) setConfirming(false);

  const closeEditor = () => {
    setEditing(false);
    requestAnimationFrame(() => editRef.current?.focus());
  };

  function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const body: SupplierPatch = {};
    const nextName = name.trim();
    const nextNotes = notes.trim();
    if (nextName === "") {
      setError(BLANK_NAME);
      return;
    }
    if (nextName !== supplier.name) body.name = nextName;
    if (nextNotes !== (supplier.notes ?? "")) body.notes = nextNotes === "" ? null : nextNotes;
    if (Object.keys(body).length === 0) {
      closeEditor();
      return;
    }
    setError(null);
    onStart();
    update.mutate(
      { id: supplier.id, patch: body },
      { onSuccess: closeEditor, onError: (e) => setError(supplierErrorText(e)) },
    );
  }

  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-48 grow">
          <p className="font-medium">{supplier.name}</p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{countText(supplier.quotation_count)}</p>
          {supplier.notes ? <p className="text-sm text-zinc-600 dark:text-zinc-400">{supplier.notes}</p> : null}
        </div>
        {canEdit ? (
          <button
            ref={editRef}
            type="button"
            disabled={busy}
            aria-expanded={editing}
            aria-label={`Edit ${supplier.name}`}
            onClick={() => {
              if (editing) {
                closeEditor();
                return;
              }
              setName(supplier.name);
              setNotes(supplier.notes ?? "");
              setError(null);
              setEditing(true);
              onStart();
            }}
            className={BUTTON}
          >
            Edit
          </button>
        ) : null}
      </div>
      {canEdit && editing ? (
        <form className="flex flex-wrap items-end gap-3" onSubmit={save}>
          <Field
            label={`Name for ${supplier.name}`}
            required
            autoFocus
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Field label={`Notes for ${supplier.name}`} value={notes} onChange={(e) => setNotes(e.target.value)} />
          <button type="submit" disabled={busy} aria-label={update.isPending ? undefined : `Save ${supplier.name}`} className="btn">
            {update.isPending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            disabled={busy}
            aria-label={`Cancel edit ${supplier.name}`}
            onClick={() => {
              setError(null);
              closeEditor();
            }}
            className="btn"
          >
            Cancel
          </button>
        </form>
      ) : null}
      {canEdit && others.length > 0 ? (
        confirming && target ? (
          <div key="confirm" className="flex flex-wrap items-center gap-3 text-sm">
            <p className="text-amber-800 dark:text-amber-300">
              Merge {supplier.name} into {target.name}? {supplier.name} will disappear and its quotations move to {target.name}.
            </p>
            <button
              type="button"
              autoFocus
              disabled={busy}
              aria-label={`Confirm merge ${supplier.name}`}
              onClick={() => {
                if (busy || mergeSent.current) return;
                mergeSent.current = true;
                setError(null);
                onStart();
                merge.mutate(
                  { id: supplier.id, intoId: target.id, name: supplier.name, intoName: target.name },
                  {
                    onError: (e) => setError(supplierErrorText(e)),
                    onSettled: () => {
                      mergeSent.current = false;
                      setConfirming(false);
                    },
                  },
                );
              }}
              className={BUTTON}
            >
              Merge
            </button>
            <button
              type="button"
              disabled={busy}
              aria-label={`Cancel merge ${supplier.name}`}
              onClick={() => {
                setConfirming(false);
                requestAnimationFrame(() => mergeRef.current?.focus());
              }}
              className={BUTTON}
            >
              Cancel
            </button>
          </div>
        ) : (
          <div key="choose" className="flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-2">
              <span className="sr-only">Merge {supplier.name} into</span>
              <select
                value={target ? targetId : ""}
                disabled={busy}
                onChange={(e) => setTargetId(e.target.value)}
                className="input"
              >
                <option value="">Choose a supplier…</option>
                {others.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              ref={mergeRef}
              type="button"
              disabled={busy || !target}
              onClick={() => {
                setError(null);
                onStart();
                setConfirming(true);
              }}
              className={BUTTON}
            >
              Merge {supplier.name} into…
            </button>
          </div>
        )
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function SuppliersView() {
  const canEdit = useCan("review_data");
  const suppliers = useQuery(suppliersQueryOptions);
  const [merged, setMerged] = useState<string | null>(null);

  return (
    <section>
      <h1 className="mb-1 text-[22px] font-semibold leading-tight">Suppliers</h1>
      <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
        Everyone who has quoted, across all tenders. Merging combines two entries for the same company and cannot be undone.
      </p>
      {canEdit ? <CreateSupplier onStart={() => setMerged(null)} /> : null}
      {merged ? (
        <p role="status" className="mb-4 text-sm text-green-700 dark:text-green-300">
          {merged}
        </p>
      ) : null}
      {suppliers.isPending ? <p role="status" className="text-sm text-zinc-500">Loading suppliers…</p> : null}
      {suppliers.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Could not load the suppliers.{" "}
          <button type="button" onClick={() => void suppliers.refetch()} className="underline">
            Try again
          </button>
        </p>
      ) : null}
      {suppliers.data && suppliers.data.length === 0 ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">No suppliers yet. They appear when you upload a quotation.</p>
      ) : null}
      {suppliers.data && suppliers.data.length > 0 ? (
        <ul aria-label="Suppliers" className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {suppliers.data.map((s) => (
            <SupplierRow
              key={s.id}
              supplier={s}
              others={suppliers.data.filter((o) => o.id !== s.id)}
              canEdit={canEdit}
              onMerged={setMerged}
              onStart={() => setMerged(null)}
            />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
