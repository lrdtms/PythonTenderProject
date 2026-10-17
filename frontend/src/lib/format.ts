export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-ZA", { dateStyle: "medium", timeStyle: "short" });
}

/** A calendar date ("2026-10-01") for people. Empty for a missing or unreadable value. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-ZA", { dateStyle: "medium", timeZone: "UTC" });
}
