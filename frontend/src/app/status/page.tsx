import type { Metadata } from "next";

import { StatusView } from "./status-view";

export const metadata: Metadata = { title: "IntelTPS status" };

export default function StatusPage() {
  return <StatusView />;
}
