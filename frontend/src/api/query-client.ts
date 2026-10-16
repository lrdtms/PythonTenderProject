import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";

// Types the mutation meta, so a typo such as skipAuthChek fails typecheck.
declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: { skipAuthCheck?: boolean };
  }
}

// The "me" key is reserved for the session query: matching is by the first key element.
function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.isUnauthorized;
}

/** The app's query client. A 401 anywhere means the session ended (or was revoked): re-check it.
 * The mounted AuthGate observes ["me"], refetches, gets 401, clears the cache and redirects. */
export function createQueryClient(): QueryClient {
  const recheckSession = () => {
    // cancelRefetch: false, so parallel 401s share the /me fetch already running.
    void client.invalidateQueries({ queryKey: ["me"] }, { cancelRefetch: false });
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
          // Other 4xx answers will not change on retry; 408 and 429 are transient.
          !(error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) &&
          count < 2,
      },
    },
  });
  return client;
}
