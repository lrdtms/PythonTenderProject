"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, useState, type ReactNode } from "react";

import { createQueryClient } from "@/api/query-client";

/** One query client per browser tab. The Suspense boundary is required by Cache Components for
 * anything that reads a query, `useParams` or `useSearchParams` during the first render. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={<p role="status" className="p-8 text-sm text-zinc-500">Loading…</p>}>
        {children}
      </Suspense>
    </QueryClientProvider>
  );
}
