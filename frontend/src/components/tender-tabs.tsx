import { TabLink } from "@/components/tab-link";

export type TenderSection = "documents" | "checklist" | "suppliers" | "estimate";

/** The sections of one tender, shown on every page that belongs to it. */
export function TenderTabs({ id, current }: { id: string; current: TenderSection }) {
  return (
    <nav aria-label="Tender sections" className="mb-6 flex flex-wrap gap-x-6 border-b border-zinc-200">
      <TabLink href={`/tenders/${id}`} current={current === "documents"}>Documents</TabLink>
      <TabLink href={`/tenders/${id}/checklist`} current={current === "checklist"}>Requirements checklist</TabLink>
      <TabLink href={`/tenders/${id}/suppliers`} current={current === "suppliers"}>Compare suppliers</TabLink>
      <TabLink href={`/tenders/${id}/estimate`} current={current === "estimate"}>Estimate</TabLink>
    </nav>
  );
}
