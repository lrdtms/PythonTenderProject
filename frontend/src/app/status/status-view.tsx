"use client";

import { useEffect, useState } from "react";

type Part = "ok" | "down" | "not_configured";
type Status = { api: Part; database: Part; model: Part };

const WORDS: Record<Part, string> = { ok: "working", down: "not working", not_configured: "not set up" };
const REFRESH_MS = 15_000;

async function load(): Promise<Status> {
  const response = await fetch("/api/v1/health/status");
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as Status;
}

/** Public: no session, no shared API client. It must work when the app itself is unwell. */
export function StatusView() {
  const [status, setStatus] = useState<Status | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    const poll = () =>
      load().then(
        (s) => {
          if (live) {
            setStatus(s);
            setFailed(false);
          }
        },
        () => {
          if (live) setFailed(true);
        },
      );
    void poll();
    const timer = setInterval(() => void poll(), REFRESH_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  const dot = (part: Part) => (part === "ok" ? "bg-green-600" : part === "down" ? "bg-red-600" : "bg-zinc-400");
  const row = (label: string, part: Part) => (
    <li className="flex items-center gap-3 py-2">
      <span aria-hidden="true" className={`h-2 w-2 flex-none rounded-full ${dot(part)}`} />
      {label}: {WORDS[part]}
    </li>
  );

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
      <div className="flex items-center gap-2 text-lg font-semibold">
        <span className="shell-mark" aria-hidden="true">I</span>
        <span>IntelTPS</span>
      </div>
      <div className="w-full max-w-sm rounded-2xl border border-[var(--edge)] bg-[var(--sheet)] p-6 sm:p-8">
        <h1 className="mb-3 text-[22px] font-semibold leading-tight">IntelTPS status</h1>
        {failed ? <p role="alert" className="notice">Cannot reach the server.</p> : null}
        {status && !failed ? (
          <ul className="divide-y divide-zinc-200" aria-live="polite">
            {row("Server", status.api)}
            {row("Database", status.database)}
            {row("Language model", status.model)}
          </ul>
        ) : null}
        {!status && !failed ? <p role="status" className="text-zinc-500">Checking…</p> : null}
      </div>
    </main>
  );
}
