"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/api/errors";
import { type UsageItem, usageQueryOptions, useSwitchPlan } from "@/api/usage";
import { useCan } from "@/components/auth-gate";

function valueText(item: UsageItem): string {
  return item.resource === "storage_mb" ? `${item.used} of ${item.limit} MB` : `${item.used} of ${item.limit}`;
}

function Row({ item }: { item: UsageItem }) {
  const full = item.used >= item.limit;
  const percent = Math.min(100, Math.round((item.used / item.limit) * 100));
  return (
    <li className="mb-4">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{item.label}</span>
        <span>
          {valueText(item)}
          {item.period === "month" ? <span className="ml-2 text-zinc-500">per month</span> : null}
          {full ? <span className="ml-2 font-medium text-amber-800 dark:text-amber-300">Limit reached</span> : null}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={item.label}
        aria-valuemin={0}
        aria-valuemax={item.limit}
        aria-valuenow={Math.min(item.used, item.limit)}
        className="h-2 w-full overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800"
      >
        <div className={`h-full ${full ? "bg-amber-600" : "bg-blue-600"}`} style={{ width: `${percent}%` }} />
      </div>
    </li>
  );
}

function PlanSwitch({ current, plans }: { current: string; plans: { code: string; name: string }[] }) {
  const change = useSwitchPlan();
  const [code, setCode] = useState(current);
  return (
    <form
      className="mt-8 flex flex-wrap items-end gap-3 border-t border-zinc-200 pt-6 dark:border-zinc-800"
      onSubmit={(e) => {
        e.preventDefault();
        if (!change.isPending && code !== current) change.mutate(code);
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        Plan
        <select
          className="rounded border bg-transparent p-1"
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
            if (change.isError) change.reset();
          }}
        >
          {plans.map((p) => (
            <option key={p.code} value={p.code}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={change.isPending || code === current} className="rounded border px-3 py-2 text-sm disabled:opacity-50">
        Switch plan
      </button>
      <p className="basis-full text-xs text-zinc-500">This is a demo plan switch. No payment is taken.</p>
      {change.isError ? (
        <p role="alert" className="basis-full text-sm text-red-700 dark:text-red-300">
          {change.error instanceof ApiError ? change.error.message : "Something went wrong. Try again."}
        </p>
      ) : null}
    </form>
  );
}

export function UsageView() {
  const canSwitch = useCan("manage_members");
  const usage = useQuery(usageQueryOptions);

  return (
    <section>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Usage</h1>
      {usage.isPending ? (
        <p role="status" className="text-sm text-zinc-500">
          Loading usage…
        </p>
      ) : null}
      {usage.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {usage.error instanceof ApiError ? usage.error.message : "Something went wrong. Try again."}
        </p>
      ) : null}
      {usage.data ? (
        <>
          <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
            Your organisation is on the {usage.data.plan_name} plan. When a limit is reached, new items of that kind are refused; nothing is
            deleted.
          </p>
          <ul>
            {usage.data.items.map((item) => (
              <Row key={item.resource} item={item} />
            ))}
          </ul>
          {canSwitch ? (
            <PlanSwitch key={usage.data.plan_code} current={usage.data.plan_code} plans={usage.data.available_plans} />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
