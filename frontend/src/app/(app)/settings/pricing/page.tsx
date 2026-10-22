import { PricingForm } from "./pricing-form";

// Waits behind the client-side AuthGate, like the other app pages, so it is never in the static shell.
export const instant = false;

export default function PricingPage() {
  return <PricingForm />;
}
