import { QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";
import { ids, makeDocument, makeExtraction, makeJob, makeVersion } from "@/test/fixtures";
import { meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { DocumentCard } from "./document-card";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const JOB_URL = `/api/v1/jobs/${ids.job}`;
const EXTRACTION_URL = `/api/v1/document-versions/${ids.version}/extraction`;
const WRITE = meWith(["read", "upload_documents"]);
const failed = () => respond(200, makeJob({ status: "failed", error_code: "FILE_CORRUPT" }));

describe("DocumentCard write controls", () => {
  it("offers a new version and Retry on an active tender", async () => {
    mockApi({ [`GET ${JOB_URL}`]: failed, [`GET ${EXTRACTION_URL}`]: () => respond(200, makeExtraction([])) }, WRITE);
    renderSignedIn(<ul><DocumentCard document={makeDocument()} tenderId={ids.tender} archived={false} /></ul>);
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/new version/i)).toBeInTheDocument();
  });

  it("hides the new-version upload and Retry on an archived tender", async () => {
    mockApi({ [`GET ${JOB_URL}`]: failed, [`GET ${EXTRACTION_URL}`]: () => respond(200, makeExtraction([])) }, WRITE);
    renderSignedIn(<ul><DocumentCard document={makeDocument()} tenderId={ids.tender} archived /></ul>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/file is damaged/i);
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/new version/i)).not.toBeInTheDocument();
  });

  it("does not carry the deep-scan choice over to a new version", async () => {
    const NEW = "00000000-0000-4000-8000-0000000000aa";
    mockApi(
      {
        [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: "succeeded" })),
        [`GET ${EXTRACTION_URL}`]: () => respond(200, makeExtraction([])),
        [`GET /api/v1/document-versions/${NEW}/extraction`]: () => respond(200, makeExtraction([])),
        [`GET /api/v1/jobs/${NEW}`]: () => respond(200, makeJob({ id: NEW, status: "succeeded" })),
      },
      meWith(["read", "review_data"]),
    );
    const card = (doc: ReturnType<typeof makeDocument>) => (
      <ul>
        <DocumentCard document={doc} tenderId={ids.tender} archived={false} />
      </ul>
    );
    const { client, rerender } = renderSignedIn(card(makeDocument()));
    const box = await screen.findByRole("checkbox", { name: /deep scan/i });
    await userEvent.click(box);
    expect(box).toBeChecked();
    rerender(
      <QueryClientProvider client={client}>
        <AuthGate>{card(makeDocument({ current_version: makeVersion({ id: NEW, version_number: 2, job_id: NEW }) }))}</AuthGate>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("checkbox", { name: /deep scan/i })).not.toBeChecked();
  });
});
