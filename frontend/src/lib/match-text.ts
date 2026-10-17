import { ApiError } from "@/api/errors";
import type { MatchSuggestion } from "@/api/types";

import type { Tone } from "./status-text";

export const classificationLabel = (c: string): string => (c === "clear" ? "Clear match" : "Needs a decision");
export const classificationTone = (c: string): Tone => (c === "clear" ? "success" : "warning");

const STATUS_LABELS: Record<string, string> = { suggested: "Suggested", confirmed: "Confirmed", rejected: "Rejected" };
const STATUS_TONES: Record<string, Tone> = { suggested: "info", confirmed: "success", rejected: "danger" };
export const matchStatusLabel = (s: string): string => STATUS_LABELS[s] ?? s;
export const matchStatusTone = (s: string): Tone => STATUS_TONES[s] ?? "neutral";

const WARNING_LABELS: Record<string, string> = {
  spec_conflict: "Specification differs",
  unit_mismatch: "Unit differs",
  quote_expires_before_closing: "Quote expires before the tender closes",
  spec_multi_value: "Quote lists more than one value",
  quote_shared: "Fits another line as well",
  core_notation_differs: "Cable core notation differs (3-core vs 3C+E)",
  text_differs: "Wording differs on both sides",
  spec_one_sided: "Only one side gives a specification",
  accessory_word: "May be an accessory, not the item",
  negation: "Says something is excluded",
  number_differs: "Quantities or sizes differ",
  defining_word_missing: "One side names a feature the other does not",
  word_one_sided: "Only one side names a feature word",
};
export const warningLabel = (code: string): string => WARNING_LABELS[code] ?? code;

const VAT_WORDS = { true: "incl. VAT", false: "excl. VAT" } as const;

/** The unit price exactly as sent (a string, never formatted), with currency code and VAT basis in words. */
export function priceText(q: {
  unit_price?: string | null;
  currency?: string | null;
  prices_include_vat?: boolean | null;
}): string {
  if (q.unit_price === null || q.unit_price === undefined || q.unit_price === "") return "Price missing";
  const parts = [q.currency ? `${q.currency} ${q.unit_price}` : q.unit_price];
  parts.push(q.prices_include_vat === true || q.prices_include_vat === false ? VAT_WORDS[`${q.prices_include_vat}`] : "VAT not stated");
  if (!q.currency) parts.push("Currency not stated");
  return parts.join(" · ");
}

type Evidence = Record<string, unknown>;
const asRecord = (v: unknown): Evidence =>
  typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Evidence) : {};
const asNumber = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const asStrings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

/** One plain sentence on why a suggestion needs a decision, from its first two warnings. */
export function reasonText(suggestion: Pick<MatchSuggestion, "evidence">): string {
  const labels = asStrings(asRecord(suggestion.evidence).warnings).slice(0, 2).map(warningLabel);
  if (labels.length === 0) return "Several close candidates from this supplier.";
  if (labels.length === 1) return `${labels[0]}.`;
  return `${labels[0]}, and ${labels[1].charAt(0).toLowerCase()}${labels[1].slice(1)}.`;
}

export function matchErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "match_conflict") {
      return "Another candidate from this supplier is already confirmed for this line. Reject or reset that one first.";
    }
    if (error.code === "stale_match") return "This quotation was replaced. Reload the list.";
    if (error.code === "tender_archived") return "This tender is archived, so it is read-only.";
    if (error.code === "row_replaced") return "Replaced by a re-run. The list was reloaded.";
    if (error.code === "try_again") return "Something changed at the same time. Try again.";
    if (error.isForbidden) return "You do not have permission to review this data.";
    return error.message;
  }
  return "Something went wrong. Try again.";
}

/** The match score as a whole percent. Display only; the only number this app formats. */
export const scoreText = (score: number): string => (Number.isFinite(score) ? `${Math.round(score * 100)}%` : "");

const kindList = (list: string[]): string => list.map((k) => k.replace(/_/g, " ")).join(", ");

const UNIT_WORDS: Record<string, string> = { equal: "Same unit", mismatch: "Units differ", unknown: "Unit not known" };

/** Rows for the "why this match" panel. Every field of the evidence JSON is optional. */
export function evidenceSummary(evidence: unknown): { label: string; value: string }[] {
  const e = asRecord(evidence);
  const rows: { label: string; value: string }[] = [];
  const signals = asRecord(e.signals);
  const text = asNumber(signals.text);
  if (text !== null) rows.push({ label: "Text similarity", value: scoreText(text) });
  const spec = asNumber(signals.spec);
  if (spec !== null) rows.push({ label: "Specification agreement", value: scoreText(spec) });
  const state = asRecord(e.unit).state;
  if (typeof state === "string" && UNIT_WORDS[state]) rows.push({ label: "Unit", value: UNIT_WORDS[state] });
  const detail = asRecord(e.spec);
  const groups: [string, string[]][] = [
    ["Matching specifications", asStrings(detail.matched)],
    ["Conflicting specifications", asStrings(detail.conflicts)],
    ["Given on one side only", [...asStrings(detail.boq_only), ...asStrings(detail.quote_only)]],
  ];
  for (const [label, list] of groups) {
    if (list.length > 0) rows.push({ label, value: kindList(list) });
  }
  if (typeof e.valid_until === "string" && e.valid_until) rows.push({ label: "Valid until", value: e.valid_until });
  return rows;
}
