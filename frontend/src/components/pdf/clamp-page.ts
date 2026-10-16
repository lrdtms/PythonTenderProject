/** A page number inside 1..numPages. Non-finite or below 1 becomes 1; above the end becomes the
 * last page. PDF.js throws for an out-of-range page, so every caller goes through this. */
export function clampPage(requested: number, numPages: number): number {
  const last = Math.max(1, Math.floor(numPages));
  if (Number.isNaN(requested) || requested < 1) return 1;
  if (!Number.isFinite(requested)) return last;
  return Math.min(Math.floor(requested), last);
}
