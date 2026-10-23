"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/api/errors";
import {
  type Estimate,
  type EstimateLine,
  type EstimateSummary,
  useCreateEstimate,
  useEstimate,
  useEstimateLines,
  useEstimates,
  usePricingDefaults,
} from "@/api/estimates";
import { tenderQueryOptions } from "@/api/tenders";
import { useCan } from "@/components/auth-gate";
import { StatusBadge } from "@/components/status-badge";
import { errorText } from "@/lib/estimate-words";
import { formatDateTime } from "@/lib/format";

import { ErrorNotice } from "./error-notice";
import { LineControls } from "./line-controls";
import { LineRow } from "./line-row";
import { SettingsCard } from "./settings-card";
import { StatusActions } from "./status-actions";
import { Summary } from "./summary";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SELECT = "rounded border bg-transparent p-1 text-sm";
const BUTTON = "rounded border px-3 py-1 text-sm disabled:opacity-50";

const STATUS_LABEL: Record<string, string> = { draft: "Draft", reviewed: "Reviewed", approved: "Approved" };

export { ErrorNotice };

type Section = { name: string | null; lines: EstimateLine[] };

/** Consecutive lines with the same section share a heading, so the BoQ order is kept. */
function groupBySection(lines: EstimateLine[]): Section[] {
  const out: Section[] = [];
  for (const line of lines) {
    const last = out.at(-1);
    if (last && last.name === line.section) last.lines.push(line);
    else out.push({ name: line.section, lines: [line] });
  }
  return out;
}

function versionLabel(v: EstimateSummary): string {
  const status = STATUS_LABEL[v.status] ?? v.status;
  return `Version ${v.version} · ${status}${v.is_current_approved ? " (current approved)" : ""}`;
}

/** The draft if there is one, otherwise the newest version. */
function defaultVersion(versions: EstimateSummary[]): EstimateSummary {
  return versions.find((v) => v.status === "draft") ?? [...versions].sort((a, b) => b.version - a.version)[0];
}

function Who({ label, userId, name: given, at }: { label: string; userId: string | null; name?: string | null; at: string | null }) {
  if (!userId && !at) return null;
  const name = given || "a team member";
  return (
    <p>
      {label} by {name}
      {at ? ` on ${formatDateTime(at)}` : ""}
    </p>
  );
}

function EstimateBody({
  estimate,
  editable,
  hasDraft,
  archived,
  onCreated,
}: {
  estimate: Estimate;
  editable: boolean;
  hasDraft: boolean;
  archived: boolean;
  onCreated: (id: string) => void;
}) {
  const [status, setStatus] = useState("");
  const list = useEstimateLines(estimate.id, { status: (status || undefined) as EstimateLine["status"] | undefined });
  const frozen = estimate.status !== "draft";
  const lines = list.lines;
  const total = estimate.priced + estimate.excluded + estimate.unresolved + estimate.changed;
  const sections = groupBySection(lines);

  return (
    <>
      {frozen ? (
        <div className="mb-3 text-sm text-zinc-700 dark:text-zinc-300">
          <Who label="Reviewed" userId={estimate.reviewed_by} name={estimate.reviewed_by_name} at={estimate.reviewed_at} />
          <Who label="Approved" userId={estimate.approved_by} name={estimate.approved_by_name} at={estimate.approved_at} />
        </div>
      ) : null}

      <div className="mb-4 grid gap-4 md:grid-cols-2">
        <SettingsCard estimate={estimate} editable={editable} />
        <Summary estimate={estimate} />
      </div>

      <StatusActions estimate={estimate} hasDraft={hasDraft} archived={archived} onCreated={onCreated} />

      <div className="mb-3 flex flex-wrap items-end gap-3" role="group" aria-label="Filters">
        <label className="text-sm">
          <span className="mr-1 font-medium">Show</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={SELECT}>
            <option value="">All lines</option>
            <option value="priced">Priced</option>
            <option value="excluded">Excluded</option>
            <option value="unresolved">Unresolved</option>
            <option value="changed">Source changed</option>
          </select>
        </label>
      </div>

      {list.isPending ? <p role="status" className="text-sm text-zinc-500">Loading lines…</p> : null}
      {list.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Could not load the lines.
        </p>
      ) : null}
      {list.isSuccess && lines.length === 0 ? (
        <p className="text-sm">
          {status
            ? "No lines match this filter."
            : total === 0
              ? "This estimate has no BoQ lines yet. Upload and review a bill of quantities, then start a new version."
              : "There are no lines to show."}
        </p>
      ) : null}

      {sections.map((section, i) => (
        <section key={`${i}-${section.name ?? ""}`} className="mb-6">
          <h2 className="mb-2 text-lg font-medium">{section.name ?? "No section"}</h2>
          <ul className="space-y-3">
            {section.lines.map((line) => (
              <LineRow
                key={line.id}
                line={line}
                currency={estimate.currency}
                candidatesInControls={editable && line.quantity !== null && !line.flags.includes("quantity_missing")}
                controls={editable ? <LineControls line={line} basis={estimate.markup_basis} /> : undefined}
              />
            ))}
          </ul>
        </section>
      ))}

      {list.hasNextPage ? (
        <button type="button" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} className={BUTTON}>
          Load more lines
        </button>
      ) : null}
    </>
  );
}

function NoEstimate({ tenderId, canCreate }: { tenderId: string; canCreate: boolean }) {
  const canManagePricing = useCan("manage_pricing");
  const create = useCreateEstimate(tenderId);
  const defaults = usePricingDefaults();
  const missing =
    (defaults.error instanceof ApiError && defaults.error.code === "pricing_defaults_missing") ||
    (create.error instanceof ApiError && create.error.code === "pricing_defaults_missing");
  const otherError = create.error && !(create.error instanceof ApiError && create.error.code === "pricing_defaults_missing");

  if (!canCreate) return <p className="text-sm">There is no estimate yet for this tender.</p>;
  return (
    <div>
      <p className="mb-3 text-sm">There is no estimate yet for this tender.</p>
      {missing ? (
        <p role="alert" className="mb-3 text-sm text-red-700 dark:text-red-300">
          {errorText("pricing_defaults_missing")}{" "}
          {canManagePricing ? (
            <Link href="/settings/pricing" className="underline">
              Set the pricing defaults
            </Link>
          ) : (
            "Ask an administrator to set them."
          )}
        </p>
      ) : null}
      {otherError ? <ErrorNotice error={create.error} /> : null}
      <button type="button" disabled={create.isPending || missing} onClick={() => create.mutate()} className={BUTTON}>
        Create estimate
      </button>
    </div>
  );
}

export function EstimateView() {
  const { id } = useParams<{ id: string }>();
  const valid = typeof id === "string" && UUID.test(id);
  const canReviewData = useCan("review_data");
  const tender = useQuery({ ...tenderQueryOptions(id), enabled: valid });
  const versions = useEstimates(id, valid);
  const [picked, setPicked] = useState<string | null>(null);

  const chosen = versions.data && versions.data.length > 0 ? (versions.data.find((v) => v.id === picked) ?? defaultVersion(versions.data)) : null;
  const estimate = useEstimate(chosen?.id ?? "");

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
  const archived = tender.data.status === "archived";
  const canEdit = canReviewData && !archived;

  let body;
  if (versions.isPending) body = <p role="status" className="text-sm text-zinc-500">Loading estimate…</p>;
  else if (versions.isError)
    body = (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        Could not load the estimate.
      </p>
    );
  else if (!chosen) body = <NoEstimate tenderId={id} canCreate={canEdit} />;
  else if (estimate.isPending) body = <p role="status" className="text-sm text-zinc-500">Loading estimate…</p>;
  else if (!estimate.data)
    body = (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        Could not load the estimate.
      </p>
    );
  else {
    const e = estimate.data;
    body = (
      <>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <label className="text-sm">
            <span className="mr-1 font-medium">Version</span>
            <select value={chosen.id} onChange={(ev) => setPicked(ev.target.value)} className={SELECT}>
              {(versions.data ?? []).map((v) => (
                <option key={v.id} value={v.id}>
                  {versionLabel(v)}
                </option>
              ))}
            </select>
          </label>
          <StatusBadge
            tone={e.status === "approved" ? "success" : e.status === "reviewed" ? "info" : "warning"}
            label={STATUS_LABEL[e.status] ?? e.status}
          />
          {e.status === "reviewed" ? <StatusBadge tone="warning" label="Not approved" /> : null}
        </div>
        <EstimateBody
          key={e.id}
          estimate={e}
          editable={canEdit && e.status === "draft"}
          hasDraft={(versions.data ?? []).some((v) => v.status === "draft")}
          archived={archived}
          onCreated={setPicked}
        />
      </>
    );
  }

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link href={`/tenders/${id}`} className="underline">
          ← Back to the tender
        </Link>
      </p>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Estimate: {tender.data.title}</h1>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
        Every BoQ line with the confirmed supplier prices that may fit it, in the order the quotes were read. Prices are
        shown as quoted; no price is chosen for you.
      </p>
      {archived ? <p className="mb-4 rounded border border-zinc-400 p-3 text-sm">This tender is archived and read-only.</p> : null}
      {body}
    </section>
  );
}
