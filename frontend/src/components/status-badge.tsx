import type { Tone } from "@/lib/status-text";

const TONES: Record<Tone, string> = {
  neutral: "border-zinc-400 text-zinc-700 dark:text-zinc-300",
  info: "border-blue-500 text-blue-700 dark:text-blue-300",
  success: "border-green-600 text-green-700 dark:text-green-300",
  warning: "border-amber-500 text-amber-700 dark:text-amber-300",
  danger: "border-red-600 text-red-700 dark:text-red-300",
};

/** State is always in the text, never conveyed by colour alone. */
export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {label}
    </span>
  );
}
