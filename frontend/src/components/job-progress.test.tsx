import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeJob } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { JobProgress } from "./job-progress";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const JOB_URL = `/api/v1/jobs/${ids.job}`;

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
    const { client } = renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    // make the "documents" key active so the invalidation refetches it
    client.setQueryData(["documents", ids.tender], []);
    expect(await screen.findByRole("progressbar")).toHaveAttribute("max", "4");
    expect(await screen.findByText("Done")).toBeInTheDocument();
    const settled = callsTo(fetchMock, "GET", JOB_URL).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(settled); // polling stopped
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
});
