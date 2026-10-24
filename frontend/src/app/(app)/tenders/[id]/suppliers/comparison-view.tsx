"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ApiError } from "@/api/errors";
import { useConfirmClear, useMatchLines, useRunMatching } from "@/api/matches";
import { quotationsQueryOptions } from "@/api/quotations";
import { tenderQueryOptions } from "@/api/tenders";
import type { MatchLine as MatchLineData } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { TenderTabs } from "@/components/tender-tabs";
import { matchErrorText } from "@/lib/match-text";

import { MatchLine } from "./match-line";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SELECT = "input";
const BUTTON = "btn";

type Section = { name: string | null; lines: MatchLineData[] };

/** Consecutive lines with the same section share a heading, so the API order is kept. */
function groupBySection(lines: MatchLineData[]): Section[] {
  const out: Section[] = [];
  for (const line of lines) {
    const last = out.at(-1);
    if (last && last.name === line.boq.section) last.lines.push(line);
    else out.push({ name: line.boq.section, lines: [line] });
  }
  return out;
}

export function ComparisonView() {
  const { id } = useParams<{ id: string }>();
  const valid = typeof id === "string" && UUID.test(id);
  const canReviewData = useCan("review_data");
  const [classification, setClassification] = useState("");
  const [status, setStatus] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [onlyWithSuggestions, setOnlyWithSuggestions] = useState(false);

  const tender = useQuery({ ...tenderQueryOptions(id), enabled: valid });
  const quotations = useQuery({ ...quotationsQueryOptions(id), enabled: valid && !!tender.data });
  const list = useMatchLines(
    id,
    {
      classification: classification || undefined,
      status: status || undefined,
      supplierId: supplierId || undefined,
      onlyWithSuggestions: onlyWithSuggestions || undefined,
    },
    valid && !!tender.data,
  );
  const confirmClear = useConfirmClear(id);
  const run = useRunMatching(id);

  const suppliers = useMemo(() => {
    const map = new Map<string, string>();
    for (const q of quotations.data ?? []) map.set(q.supplier_id, q.supplier_name);
    return [...map].map(([value, name]) => ({ id: value, name })).sort((a, b) => a.name.localeCompare(b.name));
  }, [quotations.data]);

  if (!valid || (tender.error instanceof ApiError && tender.error.isNotFound)) {
    return (
      <div role="alert">
        <p className="mb-2">This tender was not found.</p>
        <Link href="/tenders" className="underline">
          Back to tenders
        </Link>
      </div>
    );
  }
  if (tender.isPending) return <p role="status" className="text-sm text-zinc-500">Loading tender…</p>;
  if (!tender.data) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        Could not load the tender.
      </p>
    );
  }

  const canReview = canReviewData && tender.data.status !== "archived";
  const lines = list.lines;
  const all = lines.flatMap((l) => l.suggestions);
  const clearOpen = all.filter((s) => s.classification === "clear" && s.status === "suggested").length;
  const awaiting = lines.filter(
    (l) => l.suggestions.some((x) => x.status === "suggested") && !l.suggestions.some((x) => x.status === "confirmed"),
  ).length;
  const confirmed = lines.filter((l) => l.suggestions.some((x) => x.status === "confirmed")).length;
  // With a classification, status or supplier filter the API still returns every line, with the
  // suggestions filtered to none; those lines are not "no supplier match".
  const suggestionFilterActive = !!(classification || status || supplierId);
  const noMatch = suggestionFilterActive ? 0 : lines.filter((l) => l.suggestions.length === 0).length;
  const busy = confirmClear.isPending || run.isPending;
  const filtered = suggestionFilterActive || onlyWithSuggestions;
  const sections = groupBySection(lines);

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link href={`/tenders/${id}`} className="text-zinc-500 hover:text-[var(--ink)]">
          ← Back to the tender
        </Link>
      </p>
      <h1 className="mb-1 text-[22px] font-semibold leading-tight">Supplier comparison: {tender.data.title}</h1>
      <TenderTabs id={id} current="suppliers" />
      <p className="mb-4 text-sm text-zinc-500">
        Each line of the bill of quantities with the supplier quotes that may fit it, in the order the quotes were read.
        Prices are shown as quoted; confirm the match you want to use.
      </p>

      <p className="num mb-4 rounded-lg bg-[var(--raised)] px-4 py-3 text-sm" aria-live="polite">
        Loaded: {lines.length} {lines.length === 1 ? "line" : "lines"} · {awaiting} awaiting a decision · {confirmed} with a confirmed match · {noMatch} with no supplier match{list.hasNextPage ? " (more lines are not loaded yet)" : ""}
      </p>

      <div className="mb-3 flex flex-wrap items-end gap-3" role="group" aria-label="Filters">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-zinc-500">Classification</span>
          <select value={classification} onChange={(e) => setClassification(e.target.value)} className={SELECT}>
            <option value="">All</option>
            <option value="clear">Clear match</option>
            <option value="ambiguous">Needs a decision</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-zinc-500">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={SELECT}>
            <option value="">All</option>
            <option value="suggested">Suggested</option>
            <option value="confirmed">Confirmed</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-zinc-500">Supplier</span>
          <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} className={SELECT}>
            <option value="">All</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyWithSuggestions} onChange={(e) => setOnlyWithSuggestions(e.target.checked)} />
          Only lines with a suggestion
        </label>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {canReview ? (
          <>
            <button
              type="button"
              disabled={clearOpen === 0 || busy}
              onClick={() => {
                run.reset();
                confirmClear.mutate();
              }}
              className="btn btn-primary"
            >
              Confirm all clear matches ({clearOpen})
            </button>
            <button type="button" disabled={busy}
              onClick={() => {
                confirmClear.reset();
                run.mutate();
              }}
              className={BUTTON}>
              Run matching again
            </button>
          </>
        ) : null}
        <button type="button" disabled={list.isFetching} onClick={() => void list.refetch()} className={BUTTON}>
          Refresh
        </button>
      </div>
      {canReview ? (
        <p className="mb-3 text-xs text-zinc-500">
          Confirms every clear match in this tender, including lines not shown. Rival matches, edited items, quotes
          expiring before closing and cable notation differences are skipped.
        </p>
      ) : null}
      <div aria-live="polite" className="mb-3 text-sm">
        {confirmClear.data ? <p>{`Confirmed ${confirmClear.data.confirmed}, skipped ${confirmClear.data.skipped}`}</p> : null}
        {confirmClear.data && confirmClear.data.skipped > 0 ? (
          <p>
            Skipped ones need an individual decision (rival matches, edited items, quotes expiring before closing, or
            cable notation differences).
          </p>
        ) : null}
        {run.isSuccess ? <p>Matching started. Use Refresh in a moment to see the new suggestions.</p> : null}
      </div>
      {confirmClear.error || run.error ? (
        <p role="alert" className="mb-3 text-sm text-red-700 dark:text-red-300">
          {matchErrorText(confirmClear.error ?? run.error)}
        </p>
      ) : null}

      {list.isPending ? <p role="status" className="text-sm text-zinc-500">Loading lines…</p> : null}
      {list.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Could not load the lines.
        </p>
      ) : null}
      {list.isSuccess && lines.length === 0 ? (
        <p className="text-sm">
          {filtered
            ? "No lines match these filters."
            : "There are no matches to compare yet. Upload a bill of quantities and supplier quotations, then run matching."}
        </p>
      ) : null}

      {sections.map((section, i) => (
        <section key={`${i}-${section.name ?? ""}`} className="mb-6">
          <h2 className="mb-2 text-base font-semibold">{section.name ?? "No section"}</h2>
          <ul className="space-y-3">
            {section.lines.map((line) => (
              <MatchLine
                key={line.boq.id}
                line={line}
                tenderId={id} canReview={canReview}
                busy={busy}
                suggestionFilterActive={suggestionFilterActive}
              />
            ))}
          </ul>
        </section>
      ))}

      {list.hasNextPage ? (
        <button
          type="button"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
          className={BUTTON}
        >
          Load more lines
        </button>
      ) : null}
    </section>
  );
}
