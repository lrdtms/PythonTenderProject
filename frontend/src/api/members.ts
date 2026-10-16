import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, patch, post } from "./client";
import type { components } from "./schema";
import type { Role } from "./types";

export type Member = components["schemas"]["MemberDTO"];
export type CreateMemberInput = components["schemas"]["CreateMemberRequest"];

export const membersQueryOptions = queryOptions({
  queryKey: ["members"] as const,
  queryFn: ({ signal }) => get<Member[]>("/api/v1/members", undefined, signal),
  staleTime: 0,
});

function useMembersMutation<V>(fn: (vars: V) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // The server decides (last-admin rule and so on), so always re-read the list afterwards,
    // success or failure.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: membersQueryOptions.queryKey });
      // A role or status change can take effect on the very next request (the API reads it live),
      // including for the person making it, so re-read who we are too.
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    // Passwords are not kept in the mutation cache after the call.
    gcTime: 0,
  });
}

export const useCreateMember = () => useMembersMutation((input: CreateMemberInput) => post<Member>("/api/v1/members", input));

export const useChangeRole = () =>
  useMembersMutation(({ id, role }: { id: string; role: Role }) => patch<Member>(`/api/v1/members/${id}/role`, { role }));

export const useSetMemberStatus = () =>
  useMembersMutation(({ id, active }: { id: string; active: boolean }) =>
    post<Member>(`/api/v1/members/${id}/${active ? "reactivate" : "deactivate"}`),
  );

export const useResetPassword = () =>
  useMembersMutation(({ id, password }: { id: string; password: string }) =>
    post<void>(`/api/v1/members/${id}/reset-password`, { password }),
  );
