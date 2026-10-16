import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeDocument, makeJob, makeTender, makeVersion } from "@/test/fixtures";
import { callsTo, errorBody, mockApi, renderSignedIn, respond } from "@/test/render";

import { TenderWorkspace } from "./tender-workspace";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: "00000000-0000-4000-8000-000000000001" }),
}));
afterEach(() => vi.unstubAllGlobals());

const TENDER = `/api/v1/tenders/${ids.tender}`;

describe("TenderWorkspace", () => {
  it("shows the tender header and its documents with version, kind, status and job progress", async () => {
    mockApi({
      [`GET ${TENDER}`]: () => respond(200, makeTender({ closing_at: "2026-11-01T10:00:00Z" })),
      [`GET ${TENDER}/documents`]: () =>
        respond(200, [
          makeDocument(),
          makeDocument({
            id: ids.user,
            title: "BoQ",
            kind: "boq",
            current_version: makeVersion({ id: ids.run, document_id: ids.user, filename: "boq.xlsx", version_number: 2, processing_status: "processing", job_id: ids.run }),
          }),
        ]),
      [`GET /api/v1/jobs/${ids.job}`]: () => respond(200, makeJob({ status: "succeeded" })),
      [`GET /api/v1/jobs/${ids.run}`]: () => respond(200, makeJob({ id: ids.run, status: "running", progress_done: 1, progress_total: 3 })),
    });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByRole("heading", { name: "Hall wiring" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: /documents/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("Tender document")).toBeInTheDocument();
    expect(within(items[0]).getByText(/pack\.pdf/)).toBeInTheDocument();
    expect(within(items[1]).getByText("Bill of quantities")).toBeInTheDocument();
    expect(within(items[1]).getByText(/version 2/i)).toBeInTheDocument();
    expect(await within(items[1]).findByRole("progressbar")).toBeInTheDocument();
  });

  it("explains an empty tender", async () => {
    mockApi({ [`GET ${TENDER}`]: () => respond(200, makeTender()), [`GET ${TENDER}/documents`]: () => respond(200, []) });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
  });

  it("says so for an unknown tender (404) instead of showing an empty page", async () => {
    mockApi({
      [`GET ${TENDER}`]: () => respond(404, errorBody("not_found", "Tender not found")),
      [`GET ${TENDER}/documents`]: () => respond(404, errorBody("not_found", "Tender not found")),
    });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
  });

  it("marks an archived tender read-only", async () => {
    mockApi({
      [`GET ${TENDER}`]: () => respond(200, makeTender({ status: "archived", archived_at: "2026-10-16T08:00:00Z" })),
      [`GET ${TENDER}/documents`]: () => respond(200, []),
    });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByText(/archived.*read-only/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^file/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^upload/i })).not.toBeInTheDocument();
  });

  it("does not request the documents of a tender that was not found", async () => {
    const fetchMock = mockApi({ [`GET ${TENDER}`]: () => respond(404, errorBody("not_found", "Tender not found")) });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
    expect(callsTo(fetchMock, "GET", `${TENDER}/documents`)).toHaveLength(0);
  });
});
