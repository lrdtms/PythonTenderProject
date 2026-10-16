"use client";

import { useSearchParams } from "next/navigation";

import { PdfPage } from "@/components/pdf/pdf-page";

/** Developer spike (Slice 4 phase 2): proves PDF.js renders inside this Next build. Replaced by
 * the review screen's source viewer in phase 4, then deleted. */
export default function PdfSpikePage() {
  const params = useSearchParams();
  const version = params.get("version");
  const page = Number(params.get("page") ?? "1");
  if (!version) {
    return <p>Add ?version=&lt;document version id&gt;&amp;page=&lt;n&gt; to the address.</p>;
  }
  return (
    <section>
      <h1 className="mb-4 text-xl font-semibold">PDF.js spike</h1>
      <PdfPage url={`/api/v1/document-versions/${encodeURIComponent(version)}/file`} pageNumber={page} />
    </section>
  );
}
