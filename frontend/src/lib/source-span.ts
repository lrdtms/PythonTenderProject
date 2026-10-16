export type Span = { before: string; mark: string; after: string };

/** Split page text around a stored quote span; null when the offsets cannot be trusted. */
export function splitSpan(text: string, start: number | null, end: number | null): Span | null {
  if (start === null || end === null) return null;
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  if (start < 0 || end <= start || end > text.length) return null;
  return { before: text.slice(0, start), mark: text.slice(start, end), after: text.slice(end) };
}

/**
 * The backend stores quote offsets into the page text after it is squashed: every run of
 * whitespace becomes one space, the ends are trimmed, and it is lower-cased; offsets count code
 * points (provenance.py). This maps such an offset pair back onto the raw page text, in UTF-16
 * units, or returns null when the offsets do not fit.
 */
export function squashedToRaw(text: string, start: number | null, end: number | null): { start: number; end: number } | null {
  if (start === null || end === null || !Number.isInteger(start) || !Number.isInteger(end)) return null;
  if (start < 0 || end <= start) return null;
  // One entry per code point of the squashed text: where it came from in the raw text.
  const origin: { from: number; to: number }[] = [];
  let pendingSpace: { from: number; to: number } | null = null;
  let at = 0;
  for (const ch of text) {
    const next = at + ch.length;
    if (/\s/u.test(ch)) {
      if (origin.length > 0) pendingSpace = pendingSpace ? { from: pendingSpace.from, to: next } : { from: at, to: next };
    } else {
      if (pendingSpace) {
        origin.push(pendingSpace);
        pendingSpace = null;
      }
      const lowered = Array.from(ch.toLowerCase());
      for (let i = 0; i < lowered.length; i++) origin.push({ from: at, to: next });
    }
    at = next;
  }
  if (end > origin.length) return null;
  return { start: origin[start].from, end: origin[end - 1].to };
}

/** Raw-text split for a quote span stored against the squashed text. */
export function splitQuoteSpan(text: string, start: number | null, end: number | null): Span | null {
  const raw = squashedToRaw(text, start, end);
  return raw ? splitSpan(text, raw.start, raw.end) : null;
}
