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
    <section aria-label="Summary" className="panel p-5">
      <h2 className="mb-3 text-base font-semibold">Summary</h2>
      {estimate.incomplete ? (
        <p className="notice mb-3">
          These figures are partial: lines that are unresolved or changed are left out.
        </p>
      ) : null}
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-zinc-500">{label}</dt>
            <dd className="num text-right">
              {value}
              {estimate.incomplete ? <span className="ml-1 text-xs text-amber-700 dark:text-amber-300">(partial)</span> : null}
            </dd>
          </div>
        ))}
        <dt className="mt-2 self-start border-t border-zinc-200 pt-4 font-medium">Total inc VAT</dt>
        <dd className="num mt-2 border-t border-zinc-200 pt-3 text-right">
          <span className="text-[28px] font-semibold leading-tight">{money(t?.total_inc_vat)}</span>
          {estimate.incomplete ? <span className="ml-1 text-xs text-amber-700 dark:text-amber-300">(partial)</span> : null}
          {estimate.incomplete ? (
            <span className="mt-0.5 block text-sm text-amber-700 dark:text-amber-300">
              {`Incomplete: excludes ${open} ${open === 1 ? "line" : "lines"}`}
            </span>
          ) : null}
        </dd>
      </dl>
      <p className="num mt-4 text-sm text-zinc-500">
        {estimate.priced} priced · {estimate.excluded} excluded · {estimate.unresolved} unresolved · {estimate.changed} changed
      </p>
    </section>
  );
}
