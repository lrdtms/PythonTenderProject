"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import { ApiError } from "@/api/errors";
import { meQueryOptions } from "@/api/session";
import type { Me } from "@/api/types";

const SessionContext = createContext<Me | null>(null);

/** The signed-in user. Only valid inside <AuthGate>. */
export function useSession(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error("useSession must be used inside <AuthGate>");
  return me;
}

/** UI convenience only: the API enforces permissions on every request. */
export function useCan(permission: string): boolean {
  return useSession().permissions.includes(permission);
}

export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: me, error, isPending, refetch } = useQuery(meQueryOptions);
  const unauthorized = error instanceof ApiError && error.isUnauthorized;

  useEffect(() => {
    if (unauthorized) router.replace("/login");
  }, [unauthorized, router]);

  if (isPending || unauthorized) {
    return <p role="status" className="p-8 text-sm text-zinc-500">Loading…</p>;
  }
  if (error || !me) {
    return (
      <div role="alert" className="mx-auto max-w-md p-8">
        <p className="mb-4">{error instanceof Error ? error.message : "Something went wrong."}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-100 dark:text-zinc-900"
        >
          Try again
        </button>
      </div>
    );
  }
  return <SessionContext value={me}>{children}</SessionContext>;
}
