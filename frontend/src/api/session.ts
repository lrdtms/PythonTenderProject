import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, post } from "./client";
import type { LoginInput, Me, RegisterInput } from "./types";

export const meQueryOptions = queryOptions({
  queryKey: ["me"] as const,
  queryFn: ({ signal }) => get<Me>("/api/v1/me", undefined, signal),
  retry: false,
  staleTime: 30_000,
});

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: LoginInput) => post<Me>("/api/v1/auth/login", input),
    onSuccess: (me) => queryClient.setQueryData(meQueryOptions.queryKey, me),
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RegisterInput) => post<Me>("/api/v1/auth/register", input),
    onSuccess: (me) => queryClient.setQueryData(meQueryOptions.queryKey, me),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => post<void>("/api/v1/auth/logout"),
    onSettled: () => queryClient.clear(), // drop every cached tenant row, signed in or not
  });
}
