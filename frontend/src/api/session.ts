import { type QueryClient, queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, post } from "./client";
import { ApiError } from "./errors";
import type { LoginInput, Me, RegisterInput } from "./types";

export const meQueryOptions = queryOptions({
  queryKey: ["me"] as const,
  queryFn: ({ signal }) => get<Me>("/api/v1/me", undefined, signal),
  retry: false,
  staleTime: 30_000,
});

/** A new session must not see the previous user's cached rows (same tab, different account). */
function startSession(queryClient: QueryClient, me: Me) {
  queryClient.clear();
  queryClient.setQueryData(meQueryOptions.queryKey, me);
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { skipAuthCheck: true },
    mutationFn: (input: LoginInput) => post<Me>("/api/v1/auth/login", input),
    onSuccess: (me) => startSession(queryClient, me),
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { skipAuthCheck: true },
    mutationFn: (input: RegisterInput) => post<Me>("/api/v1/auth/register", input),
    onSuccess: (me) => startSession(queryClient, me),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { skipAuthCheck: true },
    mutationFn: async () => {
      try {
        await post<void>("/api/v1/auth/logout");
      } catch (error) {
        // 401: the session is already gone, which is what signing out wants.
        if (error instanceof ApiError && error.isUnauthorized) return;
        throw error;
      }
    },
    // Only once the server has ended the session: on a failure the cookie is still valid, so the
    // user stays signed in (and sees an error) rather than being shown a fake sign-out.
    onSuccess: () => queryClient.clear(),
  });
}
