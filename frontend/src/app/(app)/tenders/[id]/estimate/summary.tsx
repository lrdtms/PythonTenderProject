import type { Estimate } from "@/api/estimates";

const ZERO = "0.00";

/** Amounts exactly as the server sent them (decimal strings). A missing figure is 0.00, never blank. */
export function Summary({ estimate }: { estimate: Estimate }) {
  const t = estimate.totals;
  const money = (v: string | undefined) => `${estimate.currency} ${v && v !== "" ? v : ZERO}`;
  const open = estimate.unresolved + estimate.changed;
  const rows: [string, string][] = [
    ["Subtotal cost", money(t?.subtotal_cost)],
    ["Markup", money(t?.markup_total)],
    ["Subtotal ex VAT", money(t?.subtotal_ex_vat)],
    ["VAT", money(t?.vat_total)],
  ];
  return (
    <section aria-label="Summary" className="rounded border border-zinc-300 p-4 dark:border-zinc-700">
      <h2 className="mb-2 text-lg font-medium">Summary</h2>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="font-medium">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        <dt className="font-medium">Total inc VAT</dt>
        <dd>
          <span className="font-semibold">{money(t?.total_inc_vat)}</span>
          {estimate.incomplete ? (
            <span className="mt-0.5 block text-amber-700 dark:text-amber-300">
              {`Incomplete: excludes ${open} ${open === 1 ? "line" : "lines"}`}
            </span>
          ) : null}
        </dd>
      </dl>
      <p className="mt-3 text-sm">
        {estimate.priced} priced · {estimate.excluded} excluded · {estimate.unresolved} unresolved · {estimate.changed} changed
      </p>
    </section>
  );
}
