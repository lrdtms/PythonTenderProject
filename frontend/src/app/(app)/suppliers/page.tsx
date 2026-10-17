import { SuppliersView } from "./suppliers-view";

// This page waits behind the client-side AuthGate (the session cookie is scoped to /api, so the
// Next server cannot see who is signed in), so it is never in the static shell. Opt out of
// instant-navigation validation; revisit if/when auth moves server-side.
export const instant = false;

export default function SuppliersPage() {
  return <SuppliersView />;
}
