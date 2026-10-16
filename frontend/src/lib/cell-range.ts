export function columnLetters(n: number): string {
  let s = "";
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) s = String.fromCharCode(65 + ((x - 1) % 26)) + s;
  return s;
}

function colNumber(letters: string): number {
  return [...letters].reduce((a, c) => a * 26 + (c.charCodeAt(0) - 64), 0);
}

export type CellRange = { firstRow: number; lastRow: number; firstCol: number; lastCol: number };

/** 1-based bounds of `A12:F12` or a single cell `B3`; null if it is not a range. */
export function parseCellRange(range: string | null): CellRange | null {
  if (!range) return null;
  const m = /^([A-Z]{1,3})(\d{1,7})(?::([A-Z]{1,3})(\d{1,7}))?$/.exec(range.trim());
  if (!m) return null;
  const c1 = colNumber(m[1]);
  const r1 = Number(m[2]);
  const c2 = m[3] ? colNumber(m[3]) : c1;
  const r2 = m[4] ? Number(m[4]) : r1;
  return { firstRow: Math.min(r1, r2), lastRow: Math.max(r1, r2), firstCol: Math.min(c1, c2), lastCol: Math.max(c1, c2) };
}
