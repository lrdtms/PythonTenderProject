"use client";

import { useEffect, useRef } from "react";

import { columnLetters, parseCellRange } from "@/lib/cell-range";

export type SheetTable = { kind: "sheet"; first_row: number; rows: string[][] };

/** Narrow an untyped API table to a sheet table, or null. */
export function asSheetTable(table: unknown): SheetTable | null {
  if (typeof table !== "object" || table === null) return null;
  const t = table as { kind?: unknown; first_row?: unknown; rows?: unknown };
  if (t.kind !== "sheet" || typeof t.first_row !== "number" || !Array.isArray(t.rows)) return null;
  return { kind: "sheet", first_row: t.first_row, rows: t.rows as string[][] };
}

type Props = { table: SheetTable; range: string | null };

/** Read-only grid. Cells in the cited range carry aria-selected and an outline, and the first
 * cited row is scrolled into view. Cell values are text nodes. */
export function SheetGrid({ table, range }: Props) {
  const bounds = parseCellRange(range);
  const firstCited = useRef<HTMLTableRowElement>(null);
  const width = table.rows.reduce((w, r) => Math.max(w, r.length), 0);
  useEffect(() => {
    firstCited.current?.scrollIntoView?.({ block: "center" });
  }, [range, table]);

  const lastRow = table.first_row + table.rows.length - 1;
  const scrollRow = bounds && bounds.lastRow >= table.first_row && bounds.firstRow <= lastRow ? Math.max(bounds.firstRow, table.first_row) : null;
  return (
    <div className="max-h-96 overflow-auto rounded border border-zinc-300 dark:border-zinc-700">
      <table className="min-w-full border-collapse text-xs">
        <thead>
          <tr>
            <th scope="col" className="sticky top-0 bg-zinc-100 px-2 py-1 dark:bg-zinc-800">
              <span className="sr-only">Row</span>
            </th>
            {Array.from({ length: width }, (_, c) => (
              <th key={c} scope="col" className="sticky top-0 bg-zinc-100 px-2 py-1 font-medium dark:bg-zinc-800">
                {columnLetters(c + 1)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((cells, r) => {
            const rowNumber = table.first_row + r;
            const rowCited = !!bounds && rowNumber >= bounds.firstRow && rowNumber <= bounds.lastRow;
            const ref = rowNumber === scrollRow ? firstCited : undefined;
            return (
              <tr key={rowNumber} ref={ref}>
                <th scope="row" className="bg-zinc-100 px-2 py-1 text-right font-normal text-zinc-500 dark:bg-zinc-800">
                  {rowNumber}
                </th>
                {Array.from({ length: width }, (_, c) => {
                  const cited = rowCited && !!bounds && c + 1 >= bounds.firstCol && c + 1 <= bounds.lastCol;
                  return (
                    <td
                      key={c}
                      aria-selected={cited || undefined}
                      className={`border border-zinc-200 px-2 py-1 dark:border-zinc-700 ${cited ? "bg-yellow-200 text-black outline outline-2 outline-yellow-600" : ""}`}
                    >
                      {cells[c] ?? ""}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
