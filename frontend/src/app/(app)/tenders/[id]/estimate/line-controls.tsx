"use client";

import { type InfiniteData, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { ApiError } from "@/api/errors";
import { type EstimateLine, type LinePut, usePriceLine, useRefreshLine } from "@/api/estimates";
import { errorText, flagText } from "@/lib/estimate-words";
import { priceText } from "@/lib/match-text";
import { type MarkupBasis, markupError } from "@/lib/rates";

const BUTTON = "rounded border px-2 py-1 text-xs disabled:opacity-50";
const INPUT = "rounded border bg-transparent p-1 text-sm";
const DECIMAL = /^\d+(\.\d+)?$/;
const decimals = (v: string) => (v.split(".")[1] ?? "").length;
const FAILED = "Something went wrong. Try again.";

/** null = valid. Text, never a number, so the exact digits typed are the digits sent. */
export function priceError(v: string): string | null {
  if (!DECIMAL.test(v)) return "Enter the price as a number, for example 125.50.";
  if (decimals(v) > 4) return "The price can have at most 4 decimals.";
  if (Number(v) <= 0) return "The price must be more than 0.";
  return null;
}

export function labourError(v: string): string | null {
  if (!DECIMAL.test(v)) return "Enter the labour rate as a number, for example 25.";
  if (decimals(v) > 4) return "The labour rate can have at most 4 decimals.";
  return null;
}

type Cache = InfiniteData<EstimateLine[]>;

/** Optimistic edit of one line in every cached lines page. Returns the rollback. */
function patchLine(client: ReturnType<typeof useQueryClient>, lineId: string, patch: Partial<EstimateLine>) {
  const before = client.getQueriesData<Cache>({ queryKey: ["estimate-lines"] });
  client.setQueriesData<Cache>({ queryKey: ["estimate-lines"] }, (data) =>
    data ? { ...data, pages: data.pages.map((p) => p.map((l) => (l.id === lineId ? { ...l, ...patch } : l))) } : data,
  );
  return () => before.forEach(([key, data]) => client.setQueryData(key, data));
}

const messageOf = (error: unknown) => (error instanceof ApiError ? errorText(error.code, error.message) : FAILED);

/** Pricing controls of one open line. Every PUT replaces the whole source, so the labour rate and markup
 * override fields are always sent along with it. */
export function LineControls({ line, basis }: { line: EstimateLine; basis: MarkupBasis }) {
  const client = useQueryClient();
  const price = usePriceLine();
  const refresh = useRefreshLine();
  const uid = useId();
  const [message, setMessage] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const [reason, setReason] = useState("");
  const [labour, setLabour] = useState(line.labour_rate ?? "");
  const [markup, setMarkup] = useState(line.markup_override_percent ?? "");
  const [seen, setSeen] = useState(`${line.labour_rate}|${line.markup_override_percent}`);
  const [acked, setAcked] = useState<Record<string, boolean>>(() =>
    line.match_suggestion_id && line.unit_mismatch_acknowledged ? { [line.match_suggestion_id]: true } : {},
  );

  // The fields follow the server's values when a refetch brings different ones.
  const server = `${line.labour_rate}|${line.markup_override_percent}`;
  if (server !== seen) {
    setSeen(server);
    setLabour(line.labour_rate ?? "");
    setMarkup(line.markup_override_percent ?? "");
  }

  const busy = price.isPending || refresh.isPending;
  const quantityMissing = line.quantity === null || line.flags.includes("quantity_missing");
  const changed = line.flags.includes("source_changed") || line.status === "changed";

  function rates(): { labour_rate: string | null; markup_override_percent: string | null } | null {
    const l = labour.trim();
    const m = markup.trim();
    const bad = (l && labourError(l)) || (m && markupError(m, basis)) || null;
    if (bad) {
      setMessage(bad);
      return null;
    }
    return { labour_rate: l || null, markup_override_percent: m || null };
  }

  function send(source: Partial<LinePut>, optimistic: Partial<EstimateLine>, acknowledge = false) {
    setMessage(null);
    const r = rates();
    if (!r) return;
    const body: LinePut = { ...source, ...r, unit_mismatch_acknowledged: acknowledge };
    const rollback = patchLine(client, line.id, { ...optimistic, ...r, unit_mismatch_acknowledged: acknowledge });
    price.mutate(
      { lineId: line.id, body },
      {
        onError: (error) => {
          rollback();
          setMessage(messageOf(error));
          if (error instanceof ApiError && error.code === "stale_match") {
            void client.invalidateQueries({ queryKey: ["estimate-lines"] });
          }
        },
      },
    );
  }

  function choose(c: EstimateLine["candidates"][number]) {
    const mismatch = c.warnings.includes("unit_mismatch");
    if (mismatch && !acked[c.match_id]) {
      setMessage(errorText("unit_mismatch_unacknowledged"));
      return;
    }
    send(
      { match_suggestion_id: c.match_id },
      {
        match_suggestion_id: c.match_id,
        price_source: "supplier",
        status: "priced",
        supplier_id: c.supplier_id,
        supplier_name: c.supplier_name,
        quoted_unit_price: c.unit_price,
        quoted_currency: c.currency,
        quoted_includes_vat: c.includes_vat,
        exclude_reason: null,
      },
      mismatch,
    );
  }

  function submitManual() {
    const v = manual.trim();
    const bad = priceError(v);
    if (bad) return setMessage(bad);
    send(
      { manual_unit_price: v },
      {
        price_source: "manual",
        status: "priced",
        quoted_unit_price: v,
        match_suggestion_id: null,
        supplier_id: null,
        supplier_name: null,
        exclude_reason: null,
      },
    );
  }

  function exclude() {
    const v = reason.trim();
    if (v.length < 1) return setMessage("Give a reason for excluding this line.");
    if (v.length > 300) return setMessage("The reason can be at most 300 characters.");
    send({ exclude_reason: v }, { price_source: "excluded", status: "excluded", exclude_reason: v, match_suggestion_id: null });
  }

  /** Saves new rates by sending the line's current source again with them. */
  function saveRates() {
    if (line.price_source === "supplier" && line.match_suggestion_id)
      send({ match_suggestion_id: line.match_suggestion_id }, {}, line.unit_mismatch_acknowledged);
    else if (line.price_source === "manual" && line.quoted_unit_price) send({ manual_unit_price: line.quoted_unit_price }, {});
    else if (line.price_source === "excluded" && line.exclude_reason) send({ exclude_reason: line.exclude_reason }, {});
    else setMessage("Choose a price for this line first, then save the rates.");
  }

  return (
    <div className="space-y-2 text-sm">
      {!quantityMissing && line.candidates.length > 0 ? (
        <fieldset disabled={busy}>
          <legend className="text-xs font-medium">Choose a supplier price</legend>
          <ul aria-label="Supplier prices" className="space-y-1">
            {line.candidates.map((c) => {
              const mismatch = c.warnings.includes("unit_mismatch");
              return (
                <li key={c.match_id} className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name={`${uid}-candidate`}
                      checked={line.match_suggestion_id === c.match_id}
                      disabled={mismatch && !acked[c.match_id]}
                      onChange={() => choose(c)}
                    />
                    <span className="font-medium">{c.supplier_name}</span>{" "}
                    <span>{priceText({ unit_price: c.unit_price, currency: c.currency, prices_include_vat: c.includes_vat })}</span>
                  </label>
                  {c.warnings.map((w) => (
                    <span key={w} className="text-xs text-amber-700 dark:text-amber-300">
                      {flagText(w)}
                    </span>
                  ))}
                  {mismatch ? (
                    <label className="flex items-center gap-1 text-xs">
                      <input
                        type="checkbox"
                        checked={!!acked[c.match_id]}
                        onChange={(e) => setAcked((a) => ({ ...a, [c.match_id]: e.target.checked }))}
                      />
                      I accept the different unit for {c.supplier_name}
                    </label>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </fieldset>
      ) : null}

      {!quantityMissing ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs">
            <span className="mr-1 font-medium">Manual unit price</span>
            <input type="text" inputMode="decimal" value={manual} onChange={(e) => setManual(e.target.value)} className={`${INPUT} w-28`} disabled={busy} />
          </label>
          <button type="button" className={BUTTON} disabled={busy} onClick={submitManual}>
            Use manual price
          </button>
        </div>
      ) : (
        <p className="text-xs">{errorText("quantity_missing")}</p>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs">
          <span className="mr-1 font-medium">Reason for excluding</span>
          <input type="text" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} className={`${INPUT} w-64`} disabled={busy} />
        </label>
        <button type="button" className={BUTTON} disabled={busy} onClick={exclude}>
          Exclude
        </button>
      </div>

      {!quantityMissing ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs">
            <span className="mr-1 font-medium">Labour rate</span>
            <input type="text" inputMode="decimal" value={labour} onChange={(e) => setLabour(e.target.value)} className={`${INPUT} w-24`} disabled={busy} />
          </label>
          <label className="text-xs">
            <span className="mr-1 font-medium">Markup override %</span>
            <input type="text" inputMode="decimal" value={markup} onChange={(e) => setMarkup(e.target.value)} className={`${INPUT} w-24`} disabled={busy} />
          </label>
          <button type="button" className={BUTTON} disabled={busy} onClick={saveRates}>
            Save rates
          </button>
        </div>
      ) : null}

      {changed ? (
        <div>
          <button
            type="button"
            className={BUTTON}
            disabled={busy}
            onClick={() => {
              setMessage(null);
              refresh.mutate(line.id, { onError: (error) => setMessage(messageOf(error)) });
            }}
          >
            Refresh
          </button>
        </div>
      ) : null}

      {message ? (
        <p role="alert" className="text-xs text-red-700 dark:text-red-300">
          {message}
        </p>
      ) : null}
    </div>
  );
}
