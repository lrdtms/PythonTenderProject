"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "@/api/errors";
import { useBoqItems, useRequirements, versionQueryOptions } from "@/api/review";
import { tenderQueryOptions } from "@/api/tenders";
import { useCan } from "@/components/auth-gate";
import { BoqRow } from "@/components/review/boq-row";
import { RequirementRow } from "@/components/review/requirement-row";
import type { ReplacedInfo, RowCommand } from "@/components/review/row-shell";
import { SourceViewer, type Source } from "@/components/source/source-viewer";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Tab = "requirements" | "boq";
type Pane = "rows" | "source";

function NotFound({ tenderId }: { tenderId: string }) {
  return (
    <div role="alert">
      <p className="mb-2">This document was not found.</p>
      <Link href={UUID.test(tenderId) ? `/tenders/${tenderId}` : "/tenders"} className="underline">
        Back to the tender
      </Link>
    </div>
  );
}

/** Keyboard shortcuts must not fire while the user is typing. */
function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.closest("form") !== null)
  );
}

export function ReviewScreen() {
  const { id: tenderId, versionId } = useParams<{ id: string; versionId: string }>();
  const valid = UUID.test(tenderId ?? "") && UUID.test(versionId ?? "");
  const canReview = useCan("review_data");
  const tender = useQuery({ ...tenderQueryOptions(tenderId), enabled: valid });
  const version = useQuery({ ...versionQueryOptions(versionId), enabled: valid });
  const requirements = useRequirements(versionId, valid && !!version.data);
  const boq = useBoqItems(versionId, valid && !!version.data);

  // The checklist links here with ?row=<requirement id>: that row starts selected.
  const linkedRow = useSearchParams().get("row");
  const [pickedTab, setTab] = useState<Tab | null>(null);
  // Until the user picks a tab, open on whichever one has rows (requirements first).
  const tab: Tab = pickedTab ?? (linkedRow ? "requirements" : requirements.isSuccess && requirements.rows.length === 0 && boq.rows.length > 0 ? "boq" : "requirements");
  const [pane, setPane] = useState<Pane>("rows");
  const [pickedId, setSelectedId] = useState<string | null>(null);
  const selectedId = pickedId ?? (linkedRow && requirements.rows.some((r) => r.id === linkedRow) ? linkedRow : null);
  const [command, setCommand] = useState<RowCommand | undefined>();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [replaced, setReplaced] = useState<string | null>(null);

  const list = tab === "requirements" ? requirements : boq;
  const rows = list.rows;
  const archived = tender.data?.status === "archived";
  const selected = rows.find((r) => r.id === selectedId) ?? null;

  const source: Source | null = useMemo(() => {
    if (!selected) return null;
    if ("evidence_quote" in selected) {
      return {
        page: selected.page_number,
        sheet: null,
        cellRange: null,
        quoteStart: selected.quote_start,
        quoteEnd: selected.quote_end,
        quote: selected.evidence_quote,
      };
    }
    return {
      page: selected.page_number,
      sheet: selected.sheet,
      cellRange: selected.cell_range,
      quoteStart: null,
      quoteEnd: null,
      quote: null,
    };
  }, [selected]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (rows.length === 0) return;
        event.preventDefault();
        const at = rows.findIndex((r) => r.id === selectedId);
        const next = event.key === "ArrowDown" ? Math.min(rows.length - 1, at + 1) : Math.max(0, at <= 0 ? 0 : at - 1);
        setSelectedId(rows[next].id);
        return;
      }
      const action = ({ c: "confirm", r: "reject", e: "edit" } as const)[event.key as "c" | "r" | "e"];
      if (!action || !canReview || archived || !selectedId || editingId) return;
      event.preventDefault();
      if (action === "edit") setEditingId(selectedId);
      else setCommand((prev) => ({ action, id: selectedId, nonce: (prev?.nonce ?? 0) + 1 }));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [rows, selectedId, canReview, archived, editingId]);

  if (!valid) return <NotFound tenderId={tenderId} />;
  if (version.isPending) return <p role="status" className="text-sm text-zinc-500">Loading document…</p>;
  if (!version.data) {
    if (version.error instanceof ApiError && version.error.isNotFound) return <NotFound tenderId={tenderId} />;
    return (
      <div role="alert">
        <p className="mb-2">Could not load the document.</p>
        <button type="button" onClick={() => void version.refetch()} className="rounded border px-3 py-1 text-sm">
          Try again
        </button>
      </div>
    );
  }
  const v = version.data;

  const onReplaced = ({ patch }: ReplacedInfo) => {
    setEditingId(null);
    const unsaved = patch
      ? ` Your change was not saved: ${Object.entries(patch)
          .map(([field, value]) => `${field} ${value === null ? "(cleared)" : String(value)}`)
          .join(", ")}.`
      : "";
    setReplaced(`A row was replaced by a re-run, so the list was reloaded.${unsaved}`);
  };
  const countLabel = (n: number, more: boolean) => (more ? `${n}+` : String(n));
  const tabButton = (value: Tab, label: string, count: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={tab === value}
      onClick={() => {
        setTab(value);
        setSelectedId(null);
      }}
      className={`rounded-t border-b-2 px-3 py-2 text-sm ${tab === value ? "border-blue-600 font-medium" : "border-transparent"}`}
    >
      {label} ({count})
    </button>
  );

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link href={`/tenders/${tenderId}`} className="underline">
          ← Back to the tender
        </Link>
      </p>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Review: {v.filename}</h1>
      {archived ? (
        <p className="mb-3 rounded border border-zinc-400 p-3 text-sm">This tender is archived and read-only.</p>
      ) : null}
      {!canReview && !archived ? (
        <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">You can read this review but not change it.</p>
      ) : null}

      {replaced ? (
        <p role="alert" className="mb-3 rounded border border-amber-500 p-3 text-sm">
          {replaced}{" "}
          <button type="button" onClick={() => setReplaced(null)} className="underline">
            Dismiss
          </button>
        </p>
      ) : null}

      <div className="mb-3 flex gap-2 lg:hidden" role="group" aria-label="Show">
        {(["rows", "source"] as const).map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={pane === p}
            onClick={() => setPane(p)}
            className={`rounded border px-3 py-1 text-sm ${pane === p ? "border-blue-600 font-medium" : ""}`}
          >
            {p === "rows" ? "Rows" : "Source"}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className={pane === "rows" ? "" : "hidden lg:block"}>
          <div role="tablist" className="mb-3 flex gap-1 border-b border-zinc-300 dark:border-zinc-700">
            {tabButton("requirements", "Requirements", countLabel(requirements.rows.length, requirements.hasNextPage))}
            {tabButton("boq", "BoQ lines", countLabel(boq.rows.length, boq.hasNextPage))}
          </div>
          {list.isPending ? <p role="status" className="text-sm text-zinc-500">Loading rows…</p> : null}
          {list.isError ? (
            <p role="alert" className="text-sm text-red-700 dark:text-red-300">
              Could not load the rows.
            </p>
          ) : null}
          {list.isSuccess && rows.length === 0 ? (
            <p className="text-sm">
              Nothing was extracted from this document yet.{" "}
              <Link href={`/tenders/${tenderId}`} className="underline">
                Run extraction on the tender page
              </Link>
              .
            </p>
          ) : null}
          <ul className="space-y-2" aria-label={tab === "requirements" ? "Requirements" : "BoQ lines"}>
            {tab === "requirements"
              ? requirements.rows.map((row) => (
                  <RequirementRow
                    key={row.id}
                    row={row}
                    versionId={versionId}
                    selected={row.id === selectedId}
                    onSelect={() => {
                      setSelectedId(row.id);
                      setPane("source");
                    }}
                    archived={archived}
                    command={command}
                    editing={editingId === row.id}
                    onEditingChange={(open) => setEditingId(open ? row.id : null)}
                    onReplaced={onReplaced}
                  />
                ))
              : boq.rows.map((row) => (
                  <BoqRow
                    key={row.id}
                    row={row}
                    versionId={versionId}
                    selected={row.id === selectedId}
                    onSelect={() => {
                      setSelectedId(row.id);
                      setPane("source");
                    }}
                    archived={archived}
                    command={command}
                    editing={editingId === row.id}
                    onEditingChange={(open) => setEditingId(open ? row.id : null)}
                    onReplaced={onReplaced}
                  />
                ))}
          </ul>
          {list.hasNextPage ? (
            <button
              type="button"
              disabled={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
              className="mt-3 rounded border px-3 py-1 text-sm disabled:opacity-50"
            >
              Load more
            </button>
          ) : null}
          <p className="mt-3 text-xs text-zinc-500">Keys: arrows move, c confirm, r reject, e edit.</p>
        </div>

        <div className={pane === "source" ? "" : "hidden lg:block"}>
          <h2 className="mb-2 text-lg font-medium">Source</h2>
          {selected ? (
            <SourceViewer versionId={versionId} fileFormat={v.file_format} source={source} />
          ) : (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">Select a row to see where it came from.</p>
          )}
        </div>
      </div>
    </section>
  );
}
