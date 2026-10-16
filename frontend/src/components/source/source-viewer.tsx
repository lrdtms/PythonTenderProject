"use client";

import { useQuery } from "@tanstack/react-query";

import { pageDetailQueryOptions, pagesQueryOptions } from "@/api/review";
import { PdfPage } from "@/components/pdf/pdf-page";
import { StatusBadge } from "@/components/status-badge";
import { parseCellRange } from "@/lib/cell-range";

import { PageText } from "./page-text";
import { SheetGrid, asSheetTable } from "./sheet-grid";

export type Source = {
  page: number | null;
  sheet: string | null;
  cellRange: string | null;
  quoteStart: number | null;
  quoteEnd: number | null;
  quote: string | null;
};

/** Rows shown either side of the cited range, so the grid has context without loading a whole sheet. */
const CONTEXT_ROWS = 20;

const Unavailable = () => (
  <p role="status" className="text-sm text-zinc-600 dark:text-zinc-400">
    Source not available for this row.
  </p>
);

const OcrBadge = () => <StatusBadge tone="warning" label="Scanned page (OCR)" />;

function PageTextSource({ versionId, page, source, label }: { versionId: string; page: number; source: Source; label?: string }) {
  const detail = useQuery(pageDetailQueryOptions(versionId, page));
  if (detail.isPending) return <p role="status" className="text-sm text-zinc-500">Loading page text…</p>;
  if (detail.isError) return <Unavailable />;
  const scanned = detail.data.text_source !== "native";
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        {label ? <span className="font-medium">{label}</span> : null}
        {scanned ? <OcrBadge /> : null}
      </div>
      <PageText text={detail.data.text} start={source.quoteStart} end={source.quoteEnd} quote={source.quote} />
    </div>
  );
}

function SheetSource({ versionId, source }: { versionId: string; source: Source }) {
  const pages = useQuery(pagesQueryOptions(versionId));
  const range = parseCellRange(source.cellRange);
  const page = pages.data
    ? (pages.data.find((p) => p.label === source.sheet) ?? (pages.data.length === 1 && !source.sheet ? pages.data[0] : undefined))
    : undefined;
  const window = range
    ? { from: Math.max(1, range.firstRow - CONTEXT_ROWS), to: range.lastRow + CONTEXT_ROWS }
    : { from: 1, to: 2 * CONTEXT_ROWS };
  const detail = useQuery({ ...pageDetailQueryOptions(versionId, page?.page_number ?? 0, window), enabled: !!page });

  if (pages.isPending) return <p role="status" className="text-sm text-zinc-500">Loading sheet…</p>;
  if (pages.isError || !page || detail.isError) return <Unavailable />;
  if (detail.isPending) return <p role="status" className="text-sm text-zinc-500">Loading sheet…</p>;
  const table = detail.data.tables.map(asSheetTable).find((t) => t !== null);
  if (!table) return <Unavailable />;
  return (
    <div className="space-y-2">
      <p className="text-sm">
        <span className="font-medium">{page.label ?? "Sheet"}</span>
        {source.cellRange ? <span className="text-zinc-600 dark:text-zinc-400"> · {source.cellRange}</span> : null}
      </p>
      <SheetGrid table={table} range={source.cellRange} />
    </div>
  );
}

type Props = { versionId: string; fileFormat: string; source: Source | null };

/** Shows where an extracted row came from. The renderer follows the file format; anything that
 * cannot be resolved says so instead of leaving a blank pane. */
export function SourceViewer({ versionId, fileFormat, source }: Props) {
  if (!source) return <Unavailable />;
  if (fileFormat === "xlsx" || fileFormat === "csv") {
    return source.sheet || fileFormat === "csv" ? <SheetSource versionId={versionId} source={source} /> : <Unavailable />;
  }
  if (source.page === null) return <Unavailable />;
  if (fileFormat === "pdf") {
    return (
      <div className="space-y-3">
        <PdfPage url={`/api/v1/document-versions/${versionId}/file`} pageNumber={source.page} />
        <PageTextSource versionId={versionId} page={source.page} source={source} label="Extracted text" />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">Text only: the original layout is not shown.</p>
      <PageTextSource versionId={versionId} page={source.page} source={source} />
    </div>
  );
}
