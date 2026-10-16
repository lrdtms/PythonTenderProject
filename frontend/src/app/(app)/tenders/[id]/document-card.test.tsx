import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ids, makeDocument, makeJob } from "@/test/fixtures";
import { meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { DocumentCard } from "./document-card";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const JOB_URL = `/api/v1/jobs/${ids.job}`;
const WRITE = meWith(["read", "upload_documents"]);
const failed = () => respond(200, makeJob({ status: "failed", error_code: "FILE_CORRUPT" }));

describe("DocumentCard write controls", () => {
  it("offers a new version and Retry on an active tender", async () => {
    mockApi({ [`GET ${JOB_URL}`]: failed }, WRITE);
    renderSignedIn(<ul><DocumentCard document={makeDocument()} tenderId={ids.tender} archived={false} /></ul>);
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/new version/i)).toBeInTheDocument();
  });

  it("hides the new-version upload and Retry on an archived tender", async () => {
    mockApi({ [`GET ${JOB_URL}`]: failed }, WRITE);
    renderSignedIn(<ul><DocumentCard document={makeDocument()} tenderId={ids.tender} archived /></ul>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/./);
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/new version/i)).not.toBeInTheDocument();
  });
});
