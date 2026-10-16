// This page waits behind the client-side AuthGate (the session cookie is scoped to /api, so the
// Next server cannot see who is signed in), so it is never in the static shell. Opt out of
// instant-navigation validation; revisit if/when auth moves server-side. A layout-level
// `instant = false` does not cover child pages, so every page under (app) needs this.
export const instant = false;

export default function TendersPage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Tenders</h1>
      <p className="mt-2 text-zinc-600 dark:text-zinc-400">
        The tender list arrives with the tender workspace (Slice 4, phase 3).
      </p>
    </section>
  );
}
