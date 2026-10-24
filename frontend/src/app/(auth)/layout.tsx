import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
      <div className="flex items-center gap-2 text-lg font-semibold">
        <span className="shell-mark" aria-hidden="true">I</span>
        <h1>IntelTPS</h1>
      </div>
      <div className="w-full max-w-sm rounded-2xl border border-[var(--edge)] bg-[var(--sheet)] p-6 sm:p-8">
        {children}
      </div>
    </main>
  );
}
