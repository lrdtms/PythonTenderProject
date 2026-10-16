export type Span = { before: string; mark: string; after: string };

/** Split page text around a stored quote span; null when the offsets cannot be trusted. */
export function splitSpan(text: string, start: number | null, end: number | null): Span | null {
  if (start === null || end === null) return null;
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  if (start < 0 || end <= start || end > text.length) return null;
  return { before: text.slice(0, start), mark: text.slice(start, end), after: text.slice(end) };
}
