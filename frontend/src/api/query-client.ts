import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.isUnauthorized;
}

/** The app's query client. A 401 anywhere means the session ended (or was revoked): re-check it.
 * The mounted AuthGate observes ["me"], refetches, gets 401, clears the cache and redirects. */
export function createQueryClient(): QueryClient {
  const recheckSession = () => {
    void client.invalidateQueries({ queryKey: ["me"] });
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isUnauthorized(error) && query.queryKey[0] !== "me") recheckSession();
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        // Login, register and logout answer 401 for ordinary reasons (wrong password, no session).
        if (isUnauthorized(error) && !mutation.meta?.skipAuthCheck) recheckSession();
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      },
    },
  });
  return client;
}
