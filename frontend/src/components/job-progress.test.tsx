import { useQuery } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { documentsQueryOptions } from "@/api/documents";
import { ids, makeDocument, makeJob, makeVersion } from "@/test/fixtures";
import { callsTo, createTestClient, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { JobProgress } from "./job-progress";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const JOB_URL = `/api/v1/jobs/${ids.job}`;
const DOCS_URL = `/api/v1/tenders/${ids.tender}/documents`;
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function VersionStatus() {
  const { data } = useQuery(documentsQueryOptions(ids.tender));
  return <span data-testid="version-status">{data?.[0]?.current_version?.processing_status ?? "none"}</span>;
}

function DocumentsObserver() {
  useQuery(documentsQueryOptions(ids.tender));
  return null;
}

describe("JobProgress", () => {
  it("polls while the job runs, shows progress, stops when it finishes and refreshes the documents", async () => {
    let calls = 0;
    const fetchMock = mockApi({
      [`GET ${JOB_URL}`]: () => {
        calls += 1;
        return respond(200, calls < 3 ? makeJob({ status: "running", progress_done: calls, progress_total: 4 }) : makeJob({ status: "succeeded" }));
      },
      [`GET /api/v1/tenders/${ids.tender}/documents`]: () => respond(200, []),
    });
    renderSignedIn(
      <>
        <DocumentsObserver />
        <JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />
      </>,
    );
    expect(await screen.findByRole("progressbar")).toHaveAttribute("max", "4");
    expect(await screen.findByText("Done")).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, "GET", DOCS_URL)).toHaveLength(2)); // initial load + one refresh
    const settled = callsTo(fetchMock, "GET", JOB_URL).length;
    await wait(120);
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(settled); // polling stopped
    expect(callsTo(fetchMock, "GET", DOCS_URL)).toHaveLength(2);
  });

  it("stops polling when the component unmounts", async () => {
    const fetchMock = mockApi({ [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: "running", progress_total: 5 })) });
    const { unmount } = renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    await screen.findByRole("progressbar");
    unmount();
    const before = callsTo(fetchMock, "GET", JOB_URL).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(before);
  });

  it("explains a failure in plain words and offers a retry that posts once", async () => {
    let retried = false;
    const fetchMock = mockApi(
      {
        [`GET ${JOB_URL}`]: () => respond(200, retried ? makeJob({ status: "queued" }) : makeJob({ status: "failed", error_code: "PDF_ENCRYPTED" })),
        [`POST ${JOB_URL}/retry`]: () => {
          retried = true;
          return respond(200, makeJob({ status: "queued" }));
        },
      },
      meWith(["read", "upload_documents"]),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/password protected/i);
    const button = screen.getByRole("button", { name: /retry/i });
    await userEvent.click(button);
    await waitFor(() => expect(screen.getByText("Waiting")).toBeInTheDocument());
    expect(callsTo(fetchMock, "POST", `${JOB_URL}/retry`)).toHaveLength(1);
  });

  it("shows warnings in plain words and no Retry button to a read-only user", async () => {
    mockApi(
      {
        [`GET ${JOB_URL}`]: () =>
          respond(200, makeJob({ status: "succeeded_with_warnings", warnings: [{ code: "OCR_FAILED", pages: [3, 4] }] })),
      },
      meWith(["read"], "reviewer"),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} />);
    expect(await screen.findByText("Pages 3, 4 could not be read.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("shows the server's message when the retry is refused", async () => {
    mockApi(
      {
        [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: "failed", error_code: "FILE_CORRUPT" })),
        [`POST ${JOB_URL}/retry`]: () => respond(409, errorBody("tender_archived", "This tender is archived.")),
      },
      meWith(["read", "upload_documents"]),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} />);
    await userEvent.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText("This tender is archived.")).toBeInTheDocument();
  });

  it("does not refresh the documents for jobs that are already finished when they mount", async () => {
    const fetchMock = mockApi({
      [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: "succeeded" })),
      [`GET ${DOCS_URL}`]: () => respond(200, []),
    });
    renderSignedIn(
      <>
        <DocumentsObserver />
        <JobProgress jobId={ids.job} tenderId={ids.tender} />
        <JobProgress jobId={ids.job} tenderId={ids.tender} />
        <JobProgress jobId={ids.job} tenderId={ids.tender} />
      </>,
    );
    await waitFor(() => expect(screen.getAllByText("Done")).toHaveLength(3));
    await wait(80);
    expect(callsTo(fetchMock, "GET", DOCS_URL)).toHaveLength(1); // only the observer's own load
  });

  it("stops polling after a 404 (one request only)", async () => {
    const fetchMock = mockApi({ [`GET ${JOB_URL}`]: () => respond(404, errorBody("not_found", "Job not found")) });
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Job not found");
    await wait(120);
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(1);
  });

  it("keeps polling through a server blip", async () => {
    let calls = 0;
    mockApi({
      [`GET ${JOB_URL}`]: () => {
        calls += 1;
        return calls === 1 ? respond(500, errorBody("server_error", "Boom")) : respond(200, makeJob({ status: "succeeded" }));
      },
      [`GET ${DOCS_URL}`]: () => respond(200, []),
    });
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    expect(await screen.findByText("Done")).toBeInTheDocument();
  });

  it("gives up after repeated server errors", async () => {
    const fetchMock = mockApi({ [`GET ${JOB_URL}`]: () => respond(500, errorBody("server_error", "Boom")) });
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={10} />);
    await waitFor(() => expect(callsTo(fetchMock, "GET", JOB_URL).length).toBeGreaterThanOrEqual(5));
    await wait(100);
    const n = callsTo(fetchMock, "GET", JOB_URL).length;
    expect(n).toBeLessThanOrEqual(7);
    await wait(100);
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(n);
  });

  it("clears an old retry error on the next attempt and hides it once the job is no longer failed", async () => {
    let attempt = 0;
    let state: "failed" | "queued" = "failed";
    mockApi(
      {
        [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: state, error_code: state === "failed" ? "FILE_CORRUPT" : null })),
        [`POST ${JOB_URL}/retry`]: () => {
          attempt += 1;
          if (attempt === 1) return respond(409, errorBody("tender_archived", "This tender is archived."));
          state = "queued";
          return respond(200, makeJob({ status: "queued" }));
        },
      },
      meWith(["read", "upload_documents"]),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    await userEvent.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText("This tender is archived.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    await screen.findByText("Waiting");
    expect(screen.queryByText("This tender is archived.")).not.toBeInTheDocument();
  });

  it("refreshes the documents even when a documents fetch is already in flight (it must not join the stale one)", async () => {
    let jobCalls = 0;
    let docCalls = 0;
    mockApi({
      [`GET ${JOB_URL}`]: () => {
        jobCalls += 1;
        return respond(200, jobCalls < 2 ? makeJob({ status: "running", progress_total: 2 }) : makeJob({ status: "succeeded" }));
      },
      [`GET ${DOCS_URL}`]: async () => {
        docCalls += 1;
        if (docCalls === 1) {
          await wait(200); // read the database before the version was updated
          return respond(200, [makeDocument({ current_version: makeVersion({ processing_status: "processing" }) })]);
        }
        return respond(200, [makeDocument({ current_version: makeVersion({ processing_status: "ready" }) })]);
      },
    });
    // Cached data makes the first documents request a refetch, which is the one that can be cancelled.
    const client = createTestClient();
    client.setQueryData(["documents", ids.tender], [makeDocument({ current_version: makeVersion({ processing_status: "processing" }) })]);
    renderSignedIn(
      <>
        <VersionStatus />
        <JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />
      </>,
      client,
    );
    expect(await screen.findByText("Done")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("version-status")).toHaveTextContent("ready"), { timeout: 2000 });
  });

  it("refreshes the documents once when the job moves from waiting to running (the version becomes processing)", async () => {
    let jobCalls = 0;
    const fetchMock = mockApi({
      [`GET ${JOB_URL}`]: () => {
        jobCalls += 1;
        return respond(200, jobCalls < 2 ? makeJob({ status: "queued" }) : makeJob({ status: "running", progress_total: 3 }));
      },
      [`GET ${DOCS_URL}`]: () => respond(200, []),
    });
    renderSignedIn(
      <>
        <DocumentsObserver />
        <JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />
      </>,
    );
    await screen.findByRole("progressbar");
    await wait(150);
    expect(callsTo(fetchMock, "GET", DOCS_URL)).toHaveLength(2);
  });

  it("says the status may be out of date when polling gives up, and recovers on Check again", async () => {
    let healthy = false;
    let calls = 0;
    const fetchMock = mockApi({
      [`GET ${JOB_URL}`]: () => {
        calls += 1;
        if (healthy) return respond(200, makeJob({ status: "succeeded" }));
        if (calls === 1) return respond(200, makeJob({ status: "running", progress_total: 2 }));
        return respond(500, errorBody("server_error", "Boom"));
      },
      [`GET ${DOCS_URL}`]: () => respond(200, []),
    });
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={10} />);
    expect(await screen.findByText("Could not refresh the status.", undefined, { timeout: 3000 })).toBeInTheDocument();
    await wait(100);
    const n = callsTo(fetchMock, "GET", JOB_URL).length;
    await wait(100);
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(n); // gave up
    healthy = true;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(screen.queryByText("Could not refresh the status.")).not.toBeInTheDocument();
  });
});
