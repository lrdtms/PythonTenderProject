"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, useState, type ReactNode } from "react";

import { ApiError } from "@/api/errors";

/** One query client per browser tab. The Suspense boundary is required by Cache Components for
 * anything that reads a query, `useParams` or `useSearchParams` during the first render. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (count, error) =>
              !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={<p role="status" className="p-8 text-sm text-zinc-500">Loading…</p>}>
        {children}
      </Suspense>
    </QueryClientProvider>
  );
}
