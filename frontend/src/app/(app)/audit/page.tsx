import { AuditView } from "./audit-view";

// Waits behind the client-side AuthGate like the other pages, so it is never in the static shell.
export const instant = false;

export default function AuditPage() {
  return <AuditView />;
}
