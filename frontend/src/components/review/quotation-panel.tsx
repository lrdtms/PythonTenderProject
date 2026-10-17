"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { quotationsQueryOptions, useUpdateQuotation } from "@/api/quotations";
import { suppliersQueryOptions } from "@/api/suppliers";
import type { Quotation, QuotationPatch } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { formatDate } from "@/lib/format";
import { matchErrorText } from "@/lib/match-text";
import { warningText } from "@/lib/status-text";

type Vat = "include" | "exclude" | "unstated";
const vatOf = (v: boolean | null): Vat => (v === true ? "include" : v === false ? "exclude" : "unstated");
const VAT_LABELS: Record<Vat, string> = { include: "Prices include VAT", exclude: "Prices exclude VAT", unstated: "VAT not stated" };
const vatValue = (v: Vat): boolean | null => (v === "include" ? true : v === "exclude" ? false : null);

function QuotationForm({ quotation, onClose }: { quotation: Quotation; onClose: () => void }) {
  const suppliers = useQuery(suppliersQueryOptions);
  const update = useUpdateQuotation();
  const [supplierId, setSupplierId] = useState(quotation.supplier_id);
  const [reference, setReference] = useState(quotation.reference ?? "");
  const [quoteDate, setQuoteDate] = useState(quotation.quote_date ?? "");
  const [validUntil, setValidUntil] = useState(quotation.valid_until ?? "");
  const [currency, setCurrency] = useState(quotation.currency ?? "");
  const [vat, setVat] = useState<Vat>(vatOf(quotation.prices_include_vat));
  const [error, setError] = useState<string | null>(null);

  const options = suppliers.data ?? [];
  const known = options.some((s) => s.id === quotation.supplier_id);
  const currencyBad = currency !== "" && !/^[A-Z]{3}$/.test(currency);

  const submit = () => {
    const patch: QuotationPatch = {};
    if (supplierId !== quotation.supplier_id) patch.supplier_id = supplierId;
    if (reference.trim() !== (quotation.reference ?? "")) patch.reference = reference.trim() === "" ? null : reference.trim();
    if (quoteDate !== (quotation.quote_date ?? "")) patch.quote_date = quoteDate === "" ? null : quoteDate;
    if (validUntil !== (quotation.valid_until ?? "")) patch.valid_until = validUntil === "" ? null : validUntil;
    if (currency !== (quotation.currency ?? "")) patch.currency = currency === "" ? null : currency;
    if (vat !== vatOf(quotation.prices_include_vat)) patch.prices_include_vat = vatValue(vat);
    if (Object.keys(patch).length === 0) {
      onClose();
      return;
    }
    setError(null);
    update.mutate({ id: quotation.id, patch }, { onSuccess: onClose, onError: (e) => setError(matchErrorText(e)) });
  };

  const input = "mt-1 rounded border bg-transparent p-1";
  return (
    <form
      className="mt-3 space-y-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (!currencyBad) submit();
      }}
    >
      <label className="block">
        <span className="font-medium">Supplier</span>
        <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} className={`${input} block w-full max-w-sm`}>
          {known ? null : <option value={quotation.supplier_id}>{quotation.supplier_name}</option>}
          {options.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <p className="-mt-2 text-xs text-zinc-600 dark:text-zinc-400">Changing the supplier moves its matches to the new supplier.</p>
      <div className="flex flex-wrap gap-3">
        <label>
          <span className="block font-medium">Reference</span>
          <input value={reference} maxLength={200} onChange={(e) => setReference(e.target.value)} className={`${input} w-40`} />
        </label>
        <label>
          <span className="block font-medium">Quote date</span>
          <input type="date" value={quoteDate} onChange={(e) => setQuoteDate(e.target.value)} className={input} />
        </label>
        <label>
          <span className="block font-medium">Valid until</span>
          <input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} className={input} />
        </label>
        <label>
          <span className="block font-medium">Currency</span>
          <input
            value={currency}
            maxLength={3}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            aria-invalid={currencyBad}
            className={`${input} w-20`}
          />
          {currencyBad ? <span role="alert" className="block text-red-700 dark:text-red-300">Use a 3-letter code such as ZAR.</span> : null}
        </label>
      </div>
      <fieldset>
        <legend className="font-medium">VAT</legend>
        <div className="mt-1 flex flex-wrap gap-4">
          {(["include", "exclude", "unstated"] as const).map((value) => (
            <label key={value} className="flex items-center gap-1">
              <input type="radio" name="vat" value={value} checked={vat === value} onChange={() => setVat(value)} />
              {VAT_LABELS[value]}
            </label>
          ))}
        </div>
      </fieldset>
      {error ? <p role="alert" className="text-red-700 dark:text-red-300">{error}</p> : null}
      <div className="flex gap-2">
        <button type="submit" disabled={update.isPending || currencyBad} className="rounded border px-2 py-1 disabled:opacity-50">
          Save
        </button>
        <button type="button" disabled={update.isPending} onClick={onClose} className="rounded border px-2 py-1 disabled:opacity-50">
          Cancel
        </button>
      </div>
    </form>
  );
}

type Props = { tenderId: string; versionId: string; archived: boolean };

export function QuotationPanel({ tenderId, versionId, archived }: Props) {
  const canReview = useCan("review_data") && !archived;
  const quotations = useQuery(quotationsQueryOptions(tenderId));
  const [editing, setEditing] = useState(false);

  if (quotations.isPending) return <p role="status" className="mb-3 text-sm text-zinc-500">Loading quotation…</p>;
  if (quotations.isError) return <p role="alert" className="mb-3 text-sm text-red-700 dark:text-red-300">Could not load the quotation details.</p>;
  const quotation = quotations.data.find((q) => q.document_version_id === versionId);
  if (!quotation) return null;

  const missing = (value: string | null) => (value ? formatDate(value) || value : "not given");
  return (
    <section aria-label="Quotation details" className="mb-4 rounded border border-zinc-300 p-3 dark:border-zinc-700">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-medium">{quotation.supplier_name}</h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Reference {quotation.reference ?? "not given"} · Quote date {missing(quotation.quote_date)} · Valid until {missing(quotation.valid_until)} ·
            Currency {quotation.currency ?? "not given"}
          </p>
          <p className="text-sm">{VAT_LABELS[vatOf(quotation.prices_include_vat)]}</p>
        </div>
        {canReview && !editing ? (
          <button type="button" onClick={() => setEditing(true)} className="rounded border px-2 py-1 text-sm">
            Edit details
          </button>
        ) : null}
      </div>
      {quotation.flags.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm">
          {quotation.flags.map((code) => (
            <li key={code} className="rounded border border-amber-500 px-2 py-1">
              Warning: {warningText({ code })}
            </li>
          ))}
        </ul>
      ) : null}
      {editing ? <QuotationForm quotation={quotation} onClose={() => setEditing(false)} /> : null}
    </section>
  );
}
