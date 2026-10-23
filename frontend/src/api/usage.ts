import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { api, get } from "./client";
import type { components } from "./schema";

export type Usage = components["schemas"]["UsageDTO"];
export type UsageItem = components["schemas"]["UsageItem"];

export const usageQueryOptions = queryOptions({
  queryKey: ["usage"] as const,
  queryFn: ({ signal }) => get<Usage>("/api/v1/usage", undefined, signal),
  staleTime: 0,
});

/** Mock plan switch: no payment exists. The server answers with the usage under the new plan. */
export function useSwitchPlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (plan_code: string) => api<Usage>("/api/v1/usage/plan", { method: "PUT", json: { plan_code } }),
    onSuccess: (usage) => queryClient.setQueryData(usageQueryOptions.queryKey, usage),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: usageQueryOptions.queryKey }),
  });
}
