"use client";

import { useState, type FormEvent } from "react";

import { type Estimate, type EstimatePatch, usePatchEstimate } from "@/api/estimates";
import { ApiError } from "@/api/errors";
import { errorText } from "@/lib/estimate-words";
import { markupError, vatError } from "@/lib/rates";

type Basis = Estimate["markup_basis"];

const BASIS_LABEL: Record<Basis, string> = { cost: "On cost", selling_price: "On selling price" };
const INPUT = "rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700";

function failure(error: unknown): { code: string | null; text: string } {
  if (error instanceof ApiError) return { code: error.code, text: errorText(error.code, error.message) };
  return { code: null, text: "Something went wrong. Try again." };
}

function Form({ estimate, done, setDone }: { estimate: Estimate; done: boolean; setDone: (v: boolean) => void }) {
  const patch = usePatchEstimate();
  const [currency, setCurrency] = useState(estimate.currency);
  const [vat, setVat] = useState(estimate.vat_rate);
  const [basis, setBasis] = useState<Basis>(estimate.markup_basis);
  const [markup, setMarkup] = useState(estimate.markup_percent);
  const [errors, setErrors] = useState<{ currency?: string; vat?: string; markup?: string }>({});

  const error = patch.error ? failure(patch.error) : null;
  // A priced line (or one whose source changed) still carries a price, so the currency is locked.
  const locked = estimate.priced + estimate.changed > 0 || error?.code === "currency_locked";

  const touch = () => {
    if (done) setDone(false);
    if (patch.isError) patch.reset();
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    if (patch.isPending) return;
    const code = currency.trim().toUpperCase();
    setCurrency(code);
    const found: typeof errors = {};
    if (!locked && !/^[A-Z]{3}$/.test(code)) found.currency = "Currency must be 3 letters, for example ZAR.";
    const vatProblem = vatError(vat.trim());
    if (vatProblem) found.vat = vatProblem;
    const markupProblem = markupError(markup.trim(), basis);
    if (markupProblem) found.markup = markupProblem;
    setErrors(found);
    setDone(false);
    if (Object.keys(found).length > 0) return;
    const body: EstimatePatch = {};
    if (!locked && code !== estimate.currency) body.currency = code;
    if (vat.trim() !== estimate.vat_rate) body.vat_rate = vat.trim();
    if (basis !== estimate.markup_basis) body.markup_basis = basis;
    if (markup.trim() !== estimate.markup_percent) body.markup_percent = markup.trim();
    if (Object.keys(body).length === 0) return;
    patch.mutate({ id: estimate.id, patch: body }, { onSuccess: () => setDone(true) });
  }

  const err = (id: string, text?: string) =>
    text ? (
      <p id={id} className="text-sm text-red-700 dark:text-red-300">
        {text}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate aria-label="Estimate settings" className="max-w-xl space-y-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="es-currency" className="text-sm font-medium">
          Currency
        </label>
        <input
          id="es-currency"
          type="text"
          maxLength={3}
          autoComplete="off"
          disabled={locked}
          value={currency}
          onChange={(e) => (touch(), setCurrency(e.target.value))}
          aria-invalid={errors.currency ? true : undefined}
          aria-describedby={locked ? "es-currency-note" : errors.currency ? "es-currency-err" : undefined}
          className={`${INPUT} w-28 uppercase disabled:opacity-60`}
        />
        {locked ? (
          <p id="es-currency-note" className="text-xs text-zinc-600 dark:text-zinc-400">
            The currency cannot be changed while a line has a price. Clear those prices first.
          </p>
        ) : null}
        {err("es-currency-err", errors.currency)}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="es-vat" className="text-sm font-medium">
          VAT rate (%)
        </label>
        <input
          id="es-vat"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={vat}
          onChange={(e) => (touch(), setVat(e.target.value))}
          aria-invalid={errors.vat ? true : undefined}
          aria-describedby={errors.vat ? "es-vat-err" : undefined}
          className={`${INPUT} w-28`}
        />
        {err("es-vat-err", errors.vat)}
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
        <label htmlFor="es-markup" className="text-sm font-medium">
          Default markup (%)
        </label>
        <input
          id="es-markup"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={markup}
          onChange={(e) => (touch(), setMarkup(e.target.value))}
          aria-invalid={errors.markup ? true : undefined}
          aria-describedby={errors.markup ? "es-markup-err es-markup-hint" : "es-markup-hint"}
          className={`${INPUT} w-28`}
        />
        <p id="es-markup-hint" className="text-xs text-zinc-500">
          On selling price this is a margin and must be below 100. On cost it can be up to 1000.
        </p>
        {err("es-markup-err", errors.markup)}
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error.text}
        </p>
      ) : null}
      {done ? (
        <p role="status" className="text-sm text-green-700 dark:text-green-300">
          Settings saved.
        </p>
      ) : null}
      <button type="submit" disabled={patch.isPending} className="rounded border px-3 py-1 text-sm disabled:opacity-50">
        {patch.isPending ? "Saving…" : "Save settings"}
      </button>
    </form>
  );
}

/** Currency, VAT, markup basis and default markup. Editable only on a draft, by someone who may review data. */
export function SettingsCard({ estimate, editable }: { estimate: Estimate; editable: boolean }) {
  // Kept here, not in Form: a save refetches the estimate and the new values remount Form.
  const [done, setDone] = useState(false);
  return (
    <section aria-label="Settings" className="rounded border border-zinc-300 p-4 dark:border-zinc-700">
      <h2 className="mb-2 text-lg font-medium">Settings</h2>
      {editable ? (
        <Form
          key={`${estimate.currency}|${estimate.vat_rate}|${estimate.markup_basis}|${estimate.markup_percent}`}
          estimate={estimate}
          done={done}
          setDone={setDone}
        />
      ) : (
        <dl className="grid max-w-xl grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="font-medium">Currency</dt>
          <dd>{estimate.currency}</dd>
          <dt className="font-medium">VAT rate (%)</dt>
          <dd>{estimate.vat_rate}</dd>
          <dt className="font-medium">Markup basis</dt>
          <dd>{BASIS_LABEL[estimate.markup_basis]}</dd>
          <dt className="font-medium">Default markup (%)</dt>
          <dd>{estimate.markup_percent}</dd>
        </dl>
      )}
    </section>
  );
}
