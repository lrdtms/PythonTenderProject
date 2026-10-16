"use client";

/** Shown instead of silently freezing when a refresh failed but older data is still on screen. */
export function StaleNote({ message, onCheckAgain }: { message: string; onCheckAgain: () => void }) {
  return (
    <p role="status" className="flex flex-wrap items-center gap-2 text-sm text-amber-800 dark:text-amber-300">
      <span>{message}</span>
      <button type="button" onClick={onCheckAgain} className="rounded border border-current px-2 py-0.5">
        Check again
      </button>
    </p>
  );
}
