"use client";

import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { type PricingDefaults, usePricingDefaults, useSavePricingDefaults } from "@/api/estimates";
import { useCan } from "@/components/auth-gate";

type Basis = PricingDefaults["markup_basis"];

const BASIS_LABEL: Record<Basis, string> = { cost: "On cost", selling_price: "On selling price" };
const INPUT = "rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700";
const DECIMAL = /^\d+(\.\d*)?$/;

type Errors = { currency?: string; vat?: string; markup?: string };

/** Mirrors the server rules; the server stays the authority. Values are decimal text, never numbers. */
function validate(currency: string, vat: string, basis: Basis, markup: string): Errors {
  const errors: Errors = {};
  if (!/^[A-Z]{3}$/.test(currency)) errors.currency = "Currency must be 3 letters, for example ZAR.";
  const decimals = (v: string) => (v.split(".")[1] ?? "").length;
  if (!DECIMAL.test(vat)) errors.vat = "Enter the VAT rate as a number, for example 15.";
  else if (decimals(vat) > 2) errors.vat = "VAT rate can have at most 2 decimals.";
  else if (Number(vat) > 100) errors.vat = "VAT rate must be between 0 and 100.";
  if (!DECIMAL.test(markup)) errors.markup = "Enter the markup as a number, for example 10.";
  else if (decimals(markup) > 2) errors.markup = "Markup can have at most 2 decimals.";
  else if (basis === "selling_price" && Number(markup) >= 100)
    errors.markup = "On selling price the markup is a margin and must be below 100.";
  else if (basis === "cost" && Number(markup) > 1000) errors.markup = "Markup on cost must be between 0 and 1000.";
  return errors;
}

function serverMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

function EditForm({ saved }: { saved: PricingDefaults | null }) {
  const save = useSavePricingDefaults();
  const [currency, setCurrency] = useState(saved?.currency ?? "");
  const [vat, setVat] = useState(saved?.vat_rate ?? "");
  const [basis, setBasis] = useState<Basis>(saved?.markup_basis ?? "cost");
  const [markup, setMarkup] = useState(saved?.default_markup_percent ?? "");
  const [errors, setErrors] = useState<Errors>({});
  const [done, setDone] = useState(false);

  // Editing clears the previous outcome, so a stale message never sits beside new input.
  const touch = () => {
    if (done) setDone(false);
    if (save.isError) save.reset();
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    if (save.isPending) return;
    const code = currency.trim().toUpperCase();
    setCurrency(code);
    const found = validate(code, vat.trim(), basis, markup.trim());
    setErrors(found);
    setDone(false);
    if (Object.keys(found).length > 0) return;
    save.mutate(
      { currency: code, vat_rate: vat.trim(), markup_basis: basis, default_markup_percent: markup.trim() },
      { onSuccess: () => setDone(true) },
    );
  }

  const err = (id: string, text?: string) =>
    text ? (
      <p id={id} className="text-sm text-red-700 dark:text-red-300">
        {text}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate aria-label="Pricing defaults" className="max-w-xl space-y-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="pd-currency" className="text-sm font-medium">
          Currency
        </label>
        <input
          id="pd-currency"
          type="text"
          maxLength={3}
          autoComplete="off"
          value={currency}
          onChange={(e) => (touch(), setCurrency(e.target.value))}
          onBlur={() => setCurrency((c) => c.trim().toUpperCase())}
          aria-invalid={errors.currency ? true : undefined}
          aria-describedby={errors.currency ? "pd-currency-err" : "pd-currency-hint"}
          className={`${INPUT} w-28 uppercase`}
        />
        <p id="pd-currency-hint" className="text-xs text-zinc-500">
          Three letters, for example ZAR.
        </p>
        {err("pd-currency-err", errors.currency)}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="pd-vat" className="text-sm font-medium">
          VAT rate (%)
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <input
            id="pd-vat"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={vat}
            onChange={(e) => (touch(), setVat(e.target.value))}
            aria-invalid={errors.vat ? true : undefined}
            aria-describedby={errors.vat ? "pd-vat-err pd-vat-hint" : "pd-vat-hint"}
            className={`${INPUT} w-28`}
          />
          <span id="pd-vat-hint" className="text-xs text-zinc-500">
            15 is the usual South African rate
          </span>
        </div>
        {err("pd-vat-err", errors.vat)}
      </div>

      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">Markup basis</legend>
        {(Object.keys(BASIS_LABEL) as Basis[]).map((value) => (
          <label key={value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="markup_basis"
              value={value}
              checked={basis === value}
              onChange={() => (touch(), setBasis(value))}
            />
            {BASIS_LABEL[value]}
          </label>
        ))}
      </fieldset>

      <div className="flex flex-col gap-1">
        <label htmlFor="pd-markup" className="text-sm font-medium">
          Default markup (%)
        </label>
        <input
          id="pd-markup"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={markup}
          onChange={(e) => (touch(), setMarkup(e.target.value))}
          aria-invalid={errors.markup ? true : undefined}
          aria-describedby={errors.markup ? "pd-markup-err pd-markup-hint" : "pd-markup-hint"}
          className={`${INPUT} w-28`}
        />
        <p id="pd-markup-hint" className="text-xs text-zinc-500">
          On selling price this is a margin and must be below 100. On cost it can be up to 1000.
        </p>
        {err("pd-markup-err", errors.markup)}
      </div>

      {save.error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {serverMessage(save.error)}
        </p>
      ) : null}
      {done ? (
        <p role="status" className="text-sm text-green-700 dark:text-green-300">
          Pricing defaults saved.
        </p>
      ) : null}
      <button type="submit" disabled={save.isPending} className="rounded border px-3 py-1 text-sm disabled:opacity-50">
        {save.isPending ? "Saving…" : "Save pricing defaults"}
      </button>
    </form>
  );
}

function ReadOnly({ saved }: { saved: PricingDefaults | null }) {
  if (!saved) return <p>Pricing defaults have not been set yet. Ask an administrator.</p>;
  return (
    <dl className="grid max-w-xl grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
      <dt className="font-medium">Currency</dt>
      <dd>{saved.currency}</dd>
      <dt className="font-medium">VAT rate (%)</dt>
      <dd>{saved.vat_rate}</dd>
      <dt className="font-medium">Markup basis</dt>
      <dd>{BASIS_LABEL[saved.markup_basis]}</dd>
      <dt className="font-medium">Default markup (%)</dt>
      <dd>{saved.default_markup_percent}</dd>
    </dl>
  );
}

export function PricingForm() {
  const canManage = useCan("manage_pricing");
  const query = usePricingDefaults();
  const notSet = query.error instanceof ApiError && query.error.code === "pricing_defaults_missing";

  let body;
  if (query.isPending) body = <p>Loading…</p>;
  else if (query.error && !notSet)
    body = (
      <p role="alert" className="text-red-700 dark:text-red-300">
        Could not load the pricing defaults. Try again.
      </p>
    );
  else {
    const saved = query.data ?? null;
    body = canManage ? <EditForm key={saved?.updated_at ?? "none"} saved={saved} /> : <ReadOnly saved={saved} />;
  }

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">Pricing defaults</h1>
      <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
        {canManage
          ? "These values start every new estimate. Changing them does not alter estimates already created."
          : "Only an administrator can change pricing defaults."}
      </p>
      {body}
    </div>
  );
}
