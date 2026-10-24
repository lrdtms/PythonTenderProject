import { UsageView } from "./usage-view";

// Waits behind the client-side AuthGate, like the other app pages, so it is never in the static shell.
export const instant = false;

export default function UsagePage() {
  return <UsageView />;
}
