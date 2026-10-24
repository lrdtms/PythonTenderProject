"use client";

import { useState } from "react";

import { type AuditEvent, type AuditFilters, useAuditEvents, useAuditFacets } from "@/api/audit";
import { ApiError } from "@/api/errors";
import { useCan } from "@/components/auth-gate";

const FIELD = "rounded border bg-transparent p-1 text-sm";

function words(code: string): string {
  return code.replace(/_/g, " ");
}

/** "estimate" + "approved" -> "Estimate approved". Unknown codes still read fine. */
function describe(event: Pick<AuditEvent, "entity_type" | "action">): string {
  const text = `${words(event.entity_type)} ${words(event.action)}`;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function details(metadata: AuditEvent["metadata"]): string[] {
  return Object.entries(metadata ?? {}).map(
    ([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
  );
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-ZA", { dateStyle: "medium", timeStyle: "short" });
}

export function AuditView() {
  const canView = useCan("view_audit");
  const [filters, setFilters] = useState<AuditFilters>({});
  const facets = useAuditFacets(canView);
  const events = useAuditEvents(filters, canView);

  if (!canView) {
    return (
      <div>
        <h1 className="mb-2 text-[22px] font-semibold leading-tight">Audit</h1>
        <p>You do not have access to the audit trail.</p>
      </div>
    );
  }

  const set = (key: keyof AuditFilters) => (value: string) =>
    setFilters((f) => ({ ...f, [key]: value === "" ? undefined : value }));

  return (
    <section>
      <h1 className="mb-1 text-[22px] font-semibold leading-tight">Audit</h1>
      <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">What happened in your organisation, newest first.</p>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Action
          <select className={FIELD} value={filters.action ?? ""} onChange={(e) => set("action")(e.target.value)}>
            <option value="">All</option>
            {(facets.data?.actions ?? []).map((a) => (
              <option key={a} value={a}>
                {words(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Object
          <select className={FIELD} value={filters.entityType ?? ""} onChange={(e) => set("entityType")(e.target.value)}>
            <option value="">All</option>
            {(facets.data?.entity_types ?? []).map((t) => (
              <option key={t} value={t}>
                {words(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          From
          <input type="date" className={FIELD} value={filters.from ?? ""} onChange={(e) => set("from")(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          To
          <input type="date" className={FIELD} value={filters.to ?? ""} onChange={(e) => set("to")(e.target.value)} />
        </label>
      </div>
      {events.isPending ? (
        <p role="status" className="text-sm text-zinc-500">
          Loading events…
        </p>
      ) : null}
      {events.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {events.error instanceof ApiError ? events.error.message : "Something went wrong. Try again."}
        </p>
      ) : null}
      {events.isSuccess && events.rows.length === 0 ? <p>No events match.</p> : null}
      {events.rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-300 dark:border-zinc-700">
                <th className="py-2 pr-4 font-medium">When</th>
                <th className="py-2 pr-4 font-medium">Who</th>
                <th className="py-2 pr-4 font-medium">What</th>
                <th className="py-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {events.rows.map((e) => (
                <tr key={e.id} className="border-b border-zinc-200 align-top dark:border-zinc-800">
                  <td className="whitespace-nowrap py-2 pr-4">{when(e.created_at)}</td>
                  <td className="py-2 pr-4">{e.user_name ?? "Unknown user"}</td>
                  <td className="py-2 pr-4">{describe(e)}</td>
                  <td className="py-2">
                    {details(e.metadata).map((line) => (
                      <div key={line}>{line}</div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {events.hasNextPage ? (
        <button
          type="button"
          disabled={events.isFetchingNextPage}
          onClick={() => void events.fetchNextPage()}
          className="mt-4 rounded border px-3 py-2 text-sm disabled:opacity-50"
        >
          Load more
        </button>
      ) : null}
    </section>
  );
}
