"use client";

import { useState } from "react";

import type { QuotationItem, QuotationItemPatch } from "@/api/types";
import { StatusBadge } from "@/components/status-badge";
import { validateDecimal } from "@/lib/decimal";
import { flagLabel } from "@/lib/review-text";

import { type EditorApi, type ReplacedInfo, RowShell, type RowCommand } from "./row-shell";

type Props = {
  row: QuotationItem;
  versionId: string;
  selected: boolean;
  onSelect: () => void;
  archived?: boolean;
  command?: RowCommand;
  editing?: boolean;
  onEditingChange?: (open: boolean) => void;
  onReplaced?: (info: ReplacedInfo) => void;
};

const dash = (v: string | null | undefined) => (v === null || v === undefined || v === "" ? "-" : v);
/** "10.0000" -> "10": trailing zeros after the point are noise in an input. Text only, never a number. */
const plain = (v: string | null) => (v === null ? "" : v.includes(".") ? v.replace(/\.?0+$/, "") : v);

function QuotationEditor({ row, save, cancel, saving, error }: { row: QuotationItem } & EditorApi) {
  const [description, setDescription] = useState(row.description);
  const [sku, setSku] = useState(row.sku ?? "");
  const [unit, setUnit] = useState(row.unit ?? "");
  const [quantity, setQuantity] = useState(plain(row.quantity));
  const [price, setPrice] = useState(plain(row.unit_price));
  const qErr = validateDecimal(quantity);
  const pErr = validateDecimal(price);
  const empty = description.trim() === "";
  const invalid = !!qErr || !!pErr || empty;
  const submit = () => {
    const patch: QuotationItemPatch = {};
    if (description.trim() !== row.description) patch.description = description.trim();
    if (sku !== (row.sku ?? "")) patch.sku = sku === "" ? null : sku;
    if (unit !== (row.unit ?? "")) patch.unit = unit === "" ? null : unit;
    if (quantity.trim() !== plain(row.quantity)) patch.quantity = quantity.trim() === "" ? null : quantity.trim();
    if (price.trim() !== plain(row.unit_price)) patch.unit_price = price.trim() === "" ? null : price.trim();
    if (Object.keys(patch).length === 0) cancel();
    else save(patch);
  };
  const err = "block text-red-700 dark:text-red-300";
  return (
    <form
      className="space-y-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalid) submit();
      }}
    >
      <label className="block">
        <span className="font-medium">Description</span>
        <input value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} className="mt-1 w-full rounded border bg-transparent p-2" />
      </label>
      <div className="flex flex-wrap gap-3">
        <label>
          <span className="block font-medium">SKU</span>
          <input value={sku} maxLength={100} onChange={(e) => setSku(e.target.value)} className="w-40 rounded border bg-transparent p-1" />
        </label>
        <label>
          <span className="block font-medium">Unit</span>
          <input value={unit} maxLength={30} onChange={(e) => setUnit(e.target.value)} className="w-24 rounded border bg-transparent p-1" />
        </label>
        <label>
          <span className="block font-medium">Quantity</span>
          <input type="text" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} aria-invalid={!!qErr} className="w-32 rounded border bg-transparent p-1" />
          {qErr ? <span role="alert" className={err}>{qErr}</span> : null}
        </label>
        <label>
          <span className="block font-medium">Unit price</span>
          <input type="text" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} aria-invalid={!!pErr} className="w-32 rounded border bg-transparent p-1" />
          {pErr ? <span role="alert" className={err}>{pErr}</span> : null}
        </label>
      </div>
      {empty ? <p role="alert" className={err}>The description cannot be empty.</p> : null}
      {error ? <p role="alert" className={err}>{error}</p> : null}
      <div className="flex gap-2">
        <button type="submit" disabled={saving || invalid} className="rounded border px-2 py-1 disabled:opacity-50">
          Save
        </button>
        <button type="button" disabled={saving} onClick={cancel} className="rounded border px-2 py-1 disabled:opacity-50">
          Cancel
        </button>
      </div>
    </form>
  );
}

export function QuotationRow({ row, versionId, selected, onSelect, archived = false, command, editing, onEditingChange, onReplaced }: Props) {
  // Only fields the reviewer changed (corrected_value) can differ from the AI's reading; compare
  // normalised text so "10" and "10.0000" are the same value.
  const original = (row.original_value ?? {}) as Record<string, string | null | undefined>;
  const changedKeys = row.review_status === "corrected" && row.corrected_value ? Object.keys(row.corrected_value) : [];
  const norm = (v: string | null | undefined) => plain(v ?? null);
  const was = (field: "quantity" | "unit_price" | "unit") =>
    changedKeys.includes(field) && norm(original[field]) !== norm(row[field]) ? ` (was ${dash(norm(original[field]))})` : "";
  const originalDescription =
    changedKeys.includes("description") && original.description && original.description !== row.description ? original.description : null;
  return (
    <RowShell
      kind="quotation-item"
      versionId={versionId}
      row={row}
      selected={selected}
      onSelect={onSelect}
      archived={archived}
      command={command}
      editing={editing}
      onEditingChange={onEditingChange}
      onReplaced={onReplaced}
      chips={
        <>
          {row.sku ? <span className="rounded border px-1.5 py-0.5 font-mono text-xs">{row.sku}</span> : null}
          {row.flags.map((f) => (
            <StatusBadge key={f} tone="warning" label={flagLabel(f)} />
          ))}
        </>
      }
      summary={
        <>
          <p className="text-sm">{row.description}</p>
          {originalDescription ? <p className="mt-1 text-xs text-zinc-500">Originally: {originalDescription}</p> : null}
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
            Qty {dash(plain(row.quantity))}
            {was("quantity")} · Unit {dash(row.unit)}
            {was("unit")} · {row.unit_price === null ? "Price missing" : `Price ${row.unit_price}`}
            {was("unit_price")}
          </p>
        </>
      }
      editor={(api) => <QuotationEditor row={row} {...api} />}
    />
  );
}
