import type { ReactNode } from "react";

import type { EstimateLine } from "@/api/estimates";
import { StatusBadge } from "@/components/status-badge";
import { flagText } from "@/lib/estimate-words";
import { priceText } from "@/lib/match-text";
import type { Tone } from "@/lib/status-text";

const STATUS: Record<EstimateLine["status"], { label: string; tone: Tone }> = {
  priced: { label: "Priced", tone: "success" },
  excluded: { label: "Excluded", tone: "neutral" },
  unresolved: { label: "Unresolved", tone: "warning" },
  changed: { label: "Source changed", tone: "danger" },
};

const AMOUNTS: [string, keyof EstimateLine][] = [
  ["Unit price ex VAT", "unit_price_ex_vat"],
  ["Material", "material_cost"],
  ["Labour", "labour_cost"],
  ["Markup", "markup"],
  ["Line total", "total"],
];

function chosenSource(line: EstimateLine): string | null {
  if (line.price_source === "excluded" || line.status === "excluded")
    return `Excluded: ${line.exclude_reason ?? "no reason given"}`;
  const price = priceText({
    unit_price: line.quoted_unit_price,
    currency: line.quoted_currency,
    prices_include_vat: line.quoted_includes_vat,
  });
  if (line.price_source === "supplier") return `Price from ${line.supplier_name ?? "a supplier"}: ${price}`;
  if (line.price_source === "manual") return `Manual price: ${price}`;
  return null;
}

/** One BoQ line: read-only. Candidates are shown in the order the server sent them, none chosen, none marked.
 * `controls` is the extension point for the editing controls. */
export function LineRow({
  line,
  currency,
  controls,
  candidatesInControls = false,
}: {
  line: EstimateLine;
  currency: string;
  controls?: ReactNode;
  /** The controls list the candidates themselves (as choices), so the read-only list is left out. */
  candidatesInControls?: boolean;
}) {
  // A frozen estimate keeps its chosen price but not the candidate list, so only an open line can say "none".
  const noCandidatesNote = line.price_source === "unresolved";
  const status = STATUS[line.status];
  const source = chosenSource(line);
  const amounts = AMOUNTS.filter(([, key]) => line[key] !== null && line[key] !== undefined);
  return (
    <li id={`line-${line.id}`} className="rounded border border-zinc-300 p-3 dark:border-zinc-700">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-medium">
          {line.item_no ? `${line.item_no} ` : ""}
          {line.description}
        </p>
        <StatusBadge tone={status.tone} label={status.label} />
      </div>
      <p className="mb-2 text-xs text-zinc-600 dark:text-zinc-400">
        Unit: {line.unit ?? "not given"} · Quantity: {line.quantity ?? "not given"}
      </p>
      {line.flags.length > 0 ? (
        <ul aria-label="Flags" className="mb-2 flex flex-wrap gap-2">
          {line.flags.map((flag) => (
            <li key={flag}>
              <StatusBadge tone="warning" label={flagText(flag)} />
            </li>
          ))}
        </ul>
      ) : null}
      {source ? <p className="mb-1 text-sm">{source}</p> : null}
      {amounts.length > 0 ? (
        <dl className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {amounts.map(([label, key]) => (
            <div key={key} className="flex gap-1">
              <dt className="font-medium">{label}</dt>
              <dd>{`${currency} ${line[key] as string}`}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {line.candidates.length === 0 ? (
        noCandidatesNote ? (
          <p className="text-xs text-zinc-600 dark:text-zinc-400">No confirmed supplier price for this line.</p>
        ) : null
      ) : candidatesInControls ? null : (
        <ul aria-label="Supplier prices" className="space-y-1">
          {line.candidates.map((c) => (
            <li key={c.match_id} className="text-sm">
              <span className="font-medium">{c.supplier_name}</span>{" "}
              <span>
                {priceText({ unit_price: c.unit_price, currency: c.currency, prices_include_vat: c.includes_vat })}
              </span>
              {c.warnings.map((w) => (
                <span key={w} className="ml-2 text-xs text-amber-700 dark:text-amber-300">
                  {flagText(w)}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {controls ? <div className="mt-2">{controls}</div> : null}
    </li>
  );
}
