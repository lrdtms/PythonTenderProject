import type { Tone } from "@/lib/status-text";

// Pale tint with dark ink of the same hue; the state is always in the text as well.
const TONES: Record<Tone, string> = {
  neutral: "bg-[var(--active)] text-[var(--ink)]",
  info: "bg-blue-600/10 text-blue-700 dark:bg-blue-600/25 dark:text-blue-300",
  success: "bg-green-100 text-green-950 dark:bg-green-950 dark:text-green-300",
  warning: "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-900",
  danger: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-300",
};

/** State is always in the text, never conveyed by colour alone. */
export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {label}
    </span>
  );
}
