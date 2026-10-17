"use client";

import { useDecideMatch } from "@/api/matches";
import type { MatchSuggestion } from "@/api/types";
import { StatusBadge } from "@/components/status-badge";
import { formatDate } from "@/lib/format";
import {
  classificationLabel,
  classificationTone,
  evidenceSummary,
  matchErrorText,
  matchStatusLabel,
  matchStatusTone,
  reasonText,
  scoreText,
  warningLabel,
} from "@/lib/match-text";

const BUTTON = "rounded border px-2 py-1 text-xs disabled:opacity-50";

function warningCodes(evidence: unknown): string[] {
  if (typeof evidence !== "object" || evidence === null) return [];
  const w = (evidence as Record<string, unknown>).warnings;
  return Array.isArray(w) ? w.filter((x): x is string => typeof x === "string") : [];
}

/** One supplier candidate for a BoQ line. Prices are shown exactly as the API sends them; candidates are
 * never ordered or marked by price. A stacked card on small screens, a row from md up. */
export function CandidateRow({
  suggestion,
  tenderId,
  canReview,
  busy = false,
}: {
  suggestion: MatchSuggestion;
  tenderId: string;
  canReview: boolean;
  busy?: boolean;
}) {
  const { confirm, reject, reset } = useDecideMatch(tenderId);
  const s = suggestion;
  const q = s.quotation_item;
  const pending = busy || confirm.isPending || reject.isPending || reset.isPending;
  const error = confirm.error ?? reject.error ?? reset.error;
  // One error source per row: starting any action clears the others' results first.
  const act = (m: { mutate: (id: string) => void }) => {
    confirm.reset();
    reject.reset();
    reset.reset();
    m.mutate(s.id);
  };
  const warnings = warningCodes(s.evidence);
  const evidence = evidenceSummary(s.evidence);
  const canConfirm = s.status === "suggested" || s.status === "rejected";
  const canReject = s.status === "suggested" || s.status === "confirmed";
  const canReset = s.status === "confirmed" || s.status === "rejected";
  const decided = s.decided_at ? `Decided by ${s.decided_by_name ?? "a team member"} on ${formatDate(s.decided_at)}` : null;

  return (
    <li className="rounded border border-zinc-300 p-3 dark:border-zinc-700 md:grid md:grid-cols-[minmax(0,1fr)_auto] md:items-start md:gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium">{s.supplier.name}</p>
        <p className="text-sm">{q.description}</p>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
          {q.sku ? <span className="rounded border border-zinc-400 px-1.5 py-0.5">SKU {q.sku}</span> : null}
          <span>Unit: {q.unit ?? "not given"}</span>
          <span>Quantity: {q.quantity ?? "not given"}</span>
          <span>Unit price: {q.unit_price ?? "Price missing"}</span>
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge tone={classificationTone(s.classification)} label={classificationLabel(s.classification)} />
          <StatusBadge tone={matchStatusTone(s.status)} label={matchStatusLabel(s.status)} />
          {warnings.map((w) => (
            <StatusBadge key={w} tone="warning" label={warningLabel(w)} />
          ))}
        </div>
        {s.classification !== "clear" ? <p className="mt-1 text-xs">{reasonText(s)}</p> : null}
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer underline">Why this match</summary>
          <dl className="mt-1 space-y-0.5">
            <div className="flex gap-2">
              <dt className="font-medium">Match score</dt>
              <dd>{scoreText(s.score)}</dd>
            </div>
            {evidence.map((row) => (
              <div key={row.label} className="flex gap-2">
                <dt className="font-medium">{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </details>
        {decided ? <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{decided}</p> : null}
        {error ? (
          <p role="alert" className="mt-1 text-xs text-red-700 dark:text-red-300">
            {matchErrorText(error)}
          </p>
        ) : null}
      </div>
      {canReview ? (
        <div className="mt-2 flex flex-wrap gap-2 md:mt-0">
          {canConfirm ? (
            <button type="button" disabled={pending} onClick={() => act(confirm)} className={BUTTON}>
              Confirm
            </button>
          ) : null}
          {canReject ? (
            <button type="button" disabled={pending} onClick={() => act(reject)} className={BUTTON}>
              Reject
            </button>
          ) : null}
          {canReset ? (
            <button type="button" disabled={pending} onClick={() => act(reset)} className={BUTTON}>
              Reset
            </button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
