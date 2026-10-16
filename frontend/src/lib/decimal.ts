export const DECIMAL_PATTERN = /^-?\d{1,14}(\.\d{1,4})?$/;

/** null = valid. An empty string is valid and means "clear the value". */
export function validateDecimal(text: string): string | null {
  const t = text.trim();
  if (t === "") return null;
  if (DECIMAL_PATTERN.test(t)) return null;
  if (/^-?\d{1,14}\.\d{5,}$/.test(t)) return "Use at most 4 decimal places.";
  return "Enter a plain number such as 1500 or 12.5 (no commas or letters).";
}
