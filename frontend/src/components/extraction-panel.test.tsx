import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeExtraction, makeJob, makeKind } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { ExtractionPanel } from "./extraction-panel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const STATUS = `/api/v1/document-versions/${ids.version}/extraction`;
const EXTRACT = `/api/v1/document-versions/${ids.version}/extract`;
const REVIEW = meWith(["read", "review_data"]);

describe("ExtractionPanel", () => {
  it("renders nothing until the version has finished processing", async () => {
    const fetchMock = mockApi({});
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready={false} />);
    await new Promise((r) => setTimeout(r, 30));
    expect(callsTo(fetchMock, "GET", STATUS)).toHaveLength(0);
  });

  it("shows each kind's job status and counts, hides kinds that never ran", async () => {
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([
          makeKind("boq", { status: "succeeded" }, { status: "succeeded", counts: { items: 12, pages_with_boq: 2 } }),
          makeKind("requirements", { status: "succeeded_with_warnings", warnings: [] }, {
            status: "succeeded_with_warnings",
            counts: { requirements: 7 },
            warnings: [{ code: "EVIDENCE_UNVERIFIED", count: 2 }],
          }),
        ])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText(/12 lines/i)).toBeInTheDocument();
    expect(screen.getByText(/7 requirements/i)).toBeInTheDocument();
    expect(screen.getByText(/2 requirements could not be matched/i)).toBeInTheDocument();
  });

  it("shows a quotation kind with its item count", async () => {
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([makeKind("quotation", { status: "succeeded" }, { status: "succeeded", counts: { items: 15 } })])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText("15 items")).toBeInTheDocument();
    expect(screen.getByText("Quotation")).toBeInTheDocument();
  });

  it("uses the singular for a quotation with one item", async () => {
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([makeKind("quotation", { status: "succeeded" }, { status: "succeeded", counts: { items: 1 } })])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText("1 item")).toBeInTheDocument();
  });

  it("adds the rows kept as reviewed back into the total after a re-run", async () => {
    const dup = [{ code: "DUPLICATE_OF_REVIEWED", count: 12 }];
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([
          makeKind("quotation", { status: "succeeded" }, { status: "succeeded", counts: { items: 3 }, warnings: dup }),
          makeKind("boq", { status: "succeeded" }, { status: "succeeded", counts: { items: 3 }, warnings: dup }),
        ])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText("15 items (12 kept as reviewed)")).toBeInTheDocument();
    expect(screen.getByText("15 lines (12 kept as reviewed)")).toBeInTheDocument();
  });

  it("polls while a job is active and stops when all are done", async () => {
    let n = 0;
    const fetchMock = mockApi({
      [`GET ${STATUS}`]: () => {
        n += 1;
        const job = n < 3 ? { status: "running", progress_done: 1, progress_total: 2 } : { status: "succeeded" };
        return respond(200, makeExtraction([makeKind("boq", job, n < 3 ? null : { counts: { items: 3 } })]));
      },
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={20} />);
    expect(await screen.findByText(/3 lines/i)).toBeInTheDocument();
    const settled = callsTo(fetchMock, "GET", STATUS).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", STATUS)).toHaveLength(settled);
  });

  it("shows the job's failure in plain words (not the run's status) and that BoQ output is unaffected", async () => {
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([
          makeKind("boq", { status: "succeeded" }, { counts: { items: 5 } }),
          makeKind("requirements", { status: "failed", error_code: "LLM_UNAVAILABLE" }, { status: "running" }),
        ])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText(/AI step is not available/i)).toBeInTheDocument();
    expect(screen.getByText(/5 lines/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Processing$/)).not.toBeInTheDocument();
  });

  it("re-runs with the deep-scan option, once, and refreshes the status", async () => {
    let started = false;
    const fetchMock = mockApi(
      {
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: started ? "queued" : "succeeded" }, { counts: { requirements: 1 } })])),
        [`POST ${EXTRACT}`]: () => {
          started = true;
          return respond(202, [makeJob({ job_type: "extract_requirements", status: "queued", payload: { deep_scan: true } })]);
        },
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    await userEvent.click(await screen.findByLabelText(/deep scan/i));
    const button = screen.getByRole("button", { name: /run extraction again/i });
    await userEvent.click(button);
    await waitFor(() => expect(screen.getByText("Waiting")).toBeInTheDocument());
    const posts = callsTo(fetchMock, "POST", EXTRACT);
    expect(posts).toHaveLength(1);
    expect(JSON.parse((posts[0][1] as RequestInit).body as string)).toEqual({ deep_scan: true });
  });

  it.each([
    ["extraction_options_conflict", /different options/i],
    ["tender_archived", /archived/i],
    ["not_processed", /not finished processing/i],
  ])("explains the %s refusal in plain words", async (code, pattern) => {
    mockApi(
      {
        [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "succeeded" }, { counts: { items: 1 } })])),
        [`POST ${EXTRACT}`]: () => respond(409, errorBody(code, "raw server text")),
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    await userEvent.click(await screen.findByRole("button", { name: /run extraction again/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(pattern);
  });

  it("disables the button while a job runs", async () => {
    mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "running", progress_total: 2 }, null)])) },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    expect(await screen.findByRole("button", { name: /run extraction again/i })).toBeDisabled();
  });

  it("hides the run controls from users without review_data", async () => {
    mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "succeeded" }, { counts: { items: 1 } })])) },
      meWith(["read"], "reviewer"),
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText(/1 line/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run extraction again/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/deep scan/i)).not.toBeInTheDocument();
  });

  it("hides the run controls for an archived tender", async () => {
    mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "succeeded" }, { counts: { items: 1 } })])) },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready archived />);
    expect(await screen.findByText(/1 line/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run extraction again/i })).not.toBeInTheDocument();
  });

  it("stops polling on a 4xx answer", async () => {
    let n = 0;
    const fetchMock = mockApi({
      [`GET ${STATUS}`]: () => {
        n += 1;
        return n === 1
          ? respond(200, makeExtraction([makeKind("boq", { status: "running", progress_total: 2 }, null)]))
          : respond(404, errorBody("not_found", "Not found."));
      },
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={20} />);
    await screen.findByText(/Extraction/);
    await new Promise((r) => setTimeout(r, 150));
    const settled = callsTo(fetchMock, "GET", STATUS).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", STATUS)).toHaveLength(settled);
    expect(settled).toBeLessThanOrEqual(3);
  });

  it("says the status may be out of date when polling gives up, and recovers on Check again", async () => {
    let healthy = false;
    let n = 0;
    mockApi({
      [`GET ${STATUS}`]: () => {
        n += 1;
        if (healthy) return respond(200, makeExtraction([makeKind("boq", { status: "succeeded" }, { status: "succeeded", counts: { items: 3 } })]));
        return n === 1
          ? respond(200, makeExtraction([makeKind("boq", { status: "running", progress_total: 2 }, null)]))
          : respond(500, errorBody("server_error", "Boom"));
      },
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={10} />);
    expect(await screen.findByText("Could not refresh the status.", undefined, { timeout: 3000 })).toBeInTheDocument();
    healthy = true;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("3 lines")).toBeInTheDocument();
    expect(screen.queryByText("Could not refresh the status.")).not.toBeInTheDocument();
  });
});
