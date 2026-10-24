"use client";

/** Shown instead of silently freezing when a refresh failed but older data is still on screen. */
export function StaleNote({ message, onCheckAgain }: { message: string; onCheckAgain: () => void }) {
  return (
    <p role="status" className="notice mb-4 flex flex-wrap items-center gap-3">
      <span>{message}</span>
      <button type="button" onClick={onCheckAgain} className="underline">
        Check again
      </button>
    </p>
  );
}
