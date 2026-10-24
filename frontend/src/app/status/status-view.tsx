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

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">IntelTPS status</h1>
      {failed ? <p role="alert">Cannot reach the server.</p> : null}
      {status && !failed ? (
        <ul className="space-y-1" aria-live="polite">
          <li>Server: {WORDS[status.api]}</li>
          <li>Database: {WORDS[status.database]}</li>
          <li>Language model: {WORDS[status.model]}</li>
        </ul>
      ) : null}
      {!status && !failed ? <p role="status">Checking…</p> : null}
    </main>
  );
}
