/** Placeholder rows shown while a list loads: flat grey bars at the real row height, no shimmer. */
export function SkeletonRows({ label, rows = 4, height = 56 }: { label: string; rows?: number; height?: number }) {
  return (
    <div role="status" className="space-y-2">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} aria-hidden="true" className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}
