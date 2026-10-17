import type { MatchLine as MatchLineData } from "@/api/types";

import { CandidateRow } from "./candidate-row";

export function MatchLine({
  line,
  tenderId,
  canReview,
  busy,
  suggestionFilterActive = false,
}: {
  line: MatchLineData;
  tenderId: string;
  canReview: boolean;
  busy?: boolean;
  suggestionFilterActive?: boolean;
}) {
  const b = line.boq;
  return (
    <li className="rounded border border-zinc-300 p-3 dark:border-zinc-700">
      <p className="text-sm font-medium">
        {b.item_no ? `${b.item_no} ` : ""}
        {b.description}
      </p>
      <p className="mb-2 text-xs text-zinc-600 dark:text-zinc-400">
        Unit: {b.unit ?? "not given"} · Quantity: {b.quantity ?? "not given"}
      </p>
      {line.suggestions.length === 0 ? (
        <p className="text-sm">
          {suggestionFilterActive ? "No suggestions match these filters." : "No supplier quote matches this line."}
        </p>
      ) : (
        <ul className="space-y-2">
          {line.suggestions.map((s) => (
            <CandidateRow key={s.id} suggestion={s} tenderId={tenderId} canReview={canReview} busy={busy} />
          ))}
        </ul>
      )}
    </li>
  );
}
