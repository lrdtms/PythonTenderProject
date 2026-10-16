"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useLogout } from "@/api/session";
import type { Role } from "@/api/types";

import { useSession } from "./auth-gate";

const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  estimator: "Estimator",
  project_manager: "Project manager",
  reviewer: "Reviewer",
};

export function AppShell({ children }: { children: ReactNode }) {
  const me = useSession();
  const router = useRouter();
  const logout = useLogout();
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:p-2 focus:text-black"
      >
        Skip to content
      </a>
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <nav aria-label="Main" className="flex items-center gap-6">
          <Link href="/tenders" className="text-lg font-semibold tracking-tight">
            IntelTPS
          </Link>
          <Link href="/tenders" className="text-sm hover:underline">
            Tenders
          </Link>
        </nav>
        <div className="flex items-center gap-4 text-sm">
          <span>{me.organisation_name}</span>
          <span>
            {me.name} ({ROLE_LABELS[me.role]})
          </span>
          <button
            type="button"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSuccess: () => router.replace("/login") })}
            className="rounded border border-zinc-300 px-3 py-1 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            Sign out
          </button>
        </div>
      </header>
      {logout.isError ? (
        <p role="alert" className="bg-red-100 px-4 py-2 text-sm text-red-900">
          Could not sign out. Try again.
        </p>
      ) : null}
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 p-4 sm:p-8">
        {children}
      </main>
    </div>
  );
}
