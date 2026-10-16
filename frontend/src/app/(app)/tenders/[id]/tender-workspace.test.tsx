import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeDocument, makeJob, makeTender, makeVersion } from "@/test/fixtures";
import { callsTo, errorBody, mockApi, renderSignedIn, respond } from "@/test/render";

import { TenderWorkspace } from "./tender-workspace";

const route = vi.hoisted(() => ({ id: "00000000-0000-4000-8000-000000000001" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: route.id }),
}));
afterEach(() => {
  vi.unstubAllGlobals();
  route.id = "00000000-0000-4000-8000-000000000001";
});

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

  describe("version status that lags behind a finished ingest job", () => {
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const docWith = (processing_status: "pending" | "processing" | "ready" | "failed") =>
      makeDocument({ current_version: makeVersion({ processing_status }) });

    it("refreshes the documents once when a failed job is already terminal but the version still says processing", async () => {
      let docCalls = 0;
      const fetchMock = mockApi({
        [`GET ${TENDER}`]: () => respond(200, makeTender()),
        [`GET ${TENDER}/documents`]: () => {
          docCalls += 1;
          return respond(200, [docWith(docCalls === 1 ? "processing" : "failed")]);
        },
        [`GET /api/v1/jobs/${ids.job}`]: () => respond(200, makeJob({ status: "failed", error_code: "FILE_CORRUPT" })),
      });
      renderSignedIn(<TenderWorkspace />);
      await waitFor(() => expect(within(screen.getByRole("list", { name: /documents/i })).getAllByText("Failed").length).toBeGreaterThanOrEqual(2));
      await wait(80);
      expect(callsTo(fetchMock, "GET", `${TENDER}/documents`)).toHaveLength(2);
    });

    it("does the same for a succeeded job and a pending version", async () => {
      let docCalls = 0;
      const fetchMock = mockApi({
        [`GET ${TENDER}`]: () => respond(200, makeTender()),
        [`GET ${TENDER}/documents`]: () => {
          docCalls += 1;
          return respond(200, [docWith(docCalls === 1 ? "pending" : "ready")]);
        },
        [`GET /api/v1/jobs/${ids.job}`]: () => respond(200, makeJob({ status: "succeeded" })),
      });
      renderSignedIn(<TenderWorkspace />);
      expect(await screen.findByText("Ready")).toBeInTheDocument();
      await wait(80);
      expect(callsTo(fetchMock, "GET", `${TENDER}/documents`)).toHaveLength(2);
    });

    it("never loops when the server keeps returning the stale version status", async () => {
      const fetchMock = mockApi({
        [`GET ${TENDER}`]: () => respond(200, makeTender()),
        [`GET ${TENDER}/documents`]: () => respond(200, [docWith("processing")]),
        [`GET /api/v1/jobs/${ids.job}`]: () => respond(200, makeJob({ status: "succeeded" })),
      });
      renderSignedIn(<TenderWorkspace />);
      await screen.findByText("Done");
      await wait(300);
      expect(callsTo(fetchMock, "GET", `${TENDER}/documents`).length).toBeLessThanOrEqual(2);
    });

    it("causes no extra documents request when versions already match their finished jobs", async () => {
      const fetchMock = mockApi({
        [`GET ${TENDER}`]: () => respond(200, makeTender()),
        [`GET ${TENDER}/documents`]: () => respond(200, [
          docWith("ready"),
          makeDocument({ id: ids.user, title: "B", current_version: makeVersion({ id: ids.run, document_id: ids.user, processing_status: "failed", job_id: ids.run }) }),
        ]),
        [`GET /api/v1/jobs/${ids.job}`]: () => respond(200, makeJob({ status: "succeeded" })),
        [`GET /api/v1/jobs/${ids.run}`]: () => respond(200, makeJob({ id: ids.run, status: "failed", error_code: "FILE_CORRUPT" })),
      });
      renderSignedIn(<TenderWorkspace />);
      await screen.findByText("Done");
      await wait(150);
      expect(callsTo(fetchMock, "GET", `${TENDER}/documents`)).toHaveLength(1);
    });
  });

  it("treats a malformed tender id as not found without calling the API", async () => {
    route.id = "not-a-uuid";
    const fetchMock = mockApi({});
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This tender was not found.");
    expect(fetchMock.mock.calls.every(([url]) => url === "/api/v1/me")).toBe(true);
  });

  it("offers Try again when the tender fails to load for a reason other than not found", async () => {
    let n = 0;
    mockApi({
      [`GET ${TENDER}`]: () => {
        n += 1;
        return n === 1 ? respond(500, errorBody("server_error", "The server had a problem.")) : respond(200, makeTender());
      },
      [`GET ${TENDER}/documents`]: () => respond(200, []),
    });
    renderSignedIn(<TenderWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Hall wiring" })).toBeInTheDocument();
  });

  it("keeps the documents and says they may be out of date when a refresh fails", async () => {
    let n = 0;
    mockApi({
      [`GET ${TENDER}`]: () => respond(200, makeTender()),
      [`GET ${TENDER}/documents`]: () => {
        n += 1;
        return n === 1 ? respond(200, [makeDocument({ current_version: null })]) : respond(500, errorBody("server_error", "Boom"));
      },
    });
    const { client } = renderSignedIn(<TenderWorkspace />);
    await screen.findByText("Tender pack");
    await client.refetchQueries({ queryKey: ["documents", ids.tender] });
    expect(await screen.findByText("Could not refresh the documents.")).toBeInTheDocument();
    expect(screen.getByText("Tender pack")).toBeInTheDocument();
  });
});
