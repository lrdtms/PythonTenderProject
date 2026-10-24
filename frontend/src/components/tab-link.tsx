import Link from "next/link";
import type { ReactNode } from "react";

/** A section of one tender. The active one has a 2px accent underline; the rest are grey text. */
export function TabLink({ href, current, children }: { href: string; current?: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={`-mb-px border-b-2 py-2 text-sm ${
        current ? "border-blue-600 font-medium text-[var(--ink)]" : "border-transparent text-zinc-500 hover:text-[var(--ink)]"
      }`}
    >
      {children}
    </Link>
  );
}
