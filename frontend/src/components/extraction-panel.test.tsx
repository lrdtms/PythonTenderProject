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

  describe("progress while a job is active", () => {
    const bar = (name: RegExp) => screen.getByRole("progressbar", { name });

    it("shows a determinate bar and the section count for a running requirements job", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "running", progress_done: 44, progress_total: 73 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Reading section 44 of 73")).toBeInTheDocument();
      expect(bar(/requirements extraction progress/i)).toHaveAttribute("value", "44");
      expect(bar(/requirements extraction progress/i)).toHaveAttribute("max", "73");
    });

    it("shows an indeterminate bar with no NaN while the total is still 0", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "running", progress_done: 0, progress_total: 0 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Working…")).toBeInTheDocument();
      const el = bar(/requirements extraction progress/i);
      expect(el).not.toHaveAttribute("value");
      expect(el).not.toHaveAttribute("max");
      expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    });

    it("shows the waiting text with an indeterminate bar for a queued job", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("boq", { status: "queued", progress_done: 0, progress_total: 0 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Waiting in the queue…")).toBeInTheDocument();
      expect(bar(/bill of quantities extraction progress/i)).not.toHaveAttribute("value");
    });

    it("explains a restarted run with its attempt number", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "running", progress_done: 3, progress_total: 9, attempt_count: 3 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Attempt 3")).toBeInTheDocument();
    });

    it("shows no attempt note for a first attempt", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "running", progress_done: 3, progress_total: 9, attempt_count: 1 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Reading section 3 of 9")).toBeInTheDocument();
      expect(screen.queryByText(/Attempt/)).not.toBeInTheDocument();
    });

    it("shows no progress element for a succeeded job", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "succeeded", progress_done: 73, progress_total: 73, attempt_count: 2 }, { counts: { requirements: 4 } })])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
      expect(await screen.findByText("4 requirements")).toBeInTheDocument();
      expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
      expect(screen.queryByText(/Attempt/)).not.toBeInTheDocument();
    });

    it("clamps done to the total so the bar never overflows", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "running", progress_done: 80, progress_total: 73 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Reading section 73 of 73")).toBeInTheDocument();
      expect(bar(/requirements extraction progress/i)).toHaveAttribute("value", "73");
    });

    it("treats a negative or fractional done as a safe whole number", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: "running", progress_done: -4, progress_total: 73.7 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Reading section 0 of 73")).toBeInTheDocument();
      expect(bar(/requirements extraction progress/i)).toHaveAttribute("value", "0");
      expect(bar(/requirements extraction progress/i)).toHaveAttribute("max", "73");
    });

    it("says Working for a BoQ job at 1 of 1", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("boq", { status: "running", progress_done: 1, progress_total: 1 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Working…")).toBeInTheDocument();
    });

    it("says Working for a quotation job at 0 of 1", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("quotation", { status: "running", progress_done: 0, progress_total: 1 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("Working…")).toBeInTheDocument();
    });

    it("counts steps for a BoQ job with more than one step", async () => {
      mockApi({
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("boq", { status: "running", progress_done: 2, progress_total: 4 }, null)])),
      });
      renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
      expect(await screen.findByText("2 of 4 steps")).toBeInTheDocument();
      expect(bar(/bill of quantities extraction progress/i)).toHaveAttribute("max", "4");
    });
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

describe("cancelling an extraction", () => {
  const CANCEL = (jobId: string) => `/api/v1/jobs/${jobId}/cancel`;
  const OTHER_JOB = "00000000-0000-4000-8000-000000000044";
  const cancelButtons = () => screen.queryAllByRole("button", { name: "Cancel" });
  const running = (jobId: string, status: "running" | "queued" = "running") => ({ id: jobId, status, progress_done: 1, progress_total: 4 });

  it("shows Cancel for a running job and for a queued job when the user can run extractions", async () => {
    mockApi(
      {
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([
            makeKind("boq", running(ids.job), null),
            makeKind("requirements", running(OTHER_JOB, "queued"), null),
          ])),
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await waitFor(() => expect(cancelButtons()).toHaveLength(2));
  });

  it("never shows Cancel for a finished job", async () => {
    mockApi(
      {
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([
            makeKind("boq", { status: "succeeded" }, { counts: { items: 2 } }),
            makeKind("requirements", { status: "failed", error_code: "LLM_UNAVAILABLE" }, null),
            makeKind("quotation", { status: "cancelled" }, null),
          ])),
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    expect(await screen.findByText("2 lines")).toBeInTheDocument();
    expect(cancelButtons()).toHaveLength(0);
  });

  it("hides Cancel from a reviewer", async () => {
    mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])) },
      meWith(["read"], "reviewer"),
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    expect(await screen.findByText("Processing")).toBeInTheDocument();
    expect(cancelButtons()).toHaveLength(0);
  });

  it("hides Cancel for an archived tender", async () => {
    mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])) },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready archived pollMs={1000} />);
    expect(await screen.findByText("Processing")).toBeInTheDocument();
    expect(cancelButtons()).toHaveLength(0);
  });

  it("shows a confirmation with focus on Yes, cancel and sends nothing", async () => {
    const fetchMock = mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])) },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    const group = screen.getByRole("group", { name: /confirm cancellation/i });
    expect(group).toHaveTextContent("Cancel this extraction? Work already done on this run is discarded.");
    expect(screen.getByRole("button", { name: "Yes, cancel" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Keep going" })).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", CANCEL(ids.job))).toHaveLength(0);
  });

  it("Keep going closes the confirmation without a request", async () => {
    const fetchMock = mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])) },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Keep going" }));
    expect(screen.queryByRole("group", { name: /confirm cancellation/i })).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", CANCEL(ids.job))).toHaveLength(0);
    expect(cancelButtons()).toHaveLength(1);
  });

  it("Yes, cancel posts for the right job and refetches the status", async () => {
    let cancelled = false;
    const fetchMock = mockApi(
      {
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([
            makeKind("boq", running(ids.job), null),
            makeKind("requirements", cancelled ? { id: OTHER_JOB, status: "cancelled" } : running(OTHER_JOB), null),
          ])),
        [`POST ${CANCEL(OTHER_JOB)}`]: () => {
          cancelled = true;
          return respond(200, makeJob({ id: OTHER_JOB, status: "cancelled" }));
        },
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await waitFor(() => expect(cancelButtons()).toHaveLength(2));
    const statusCalls = callsTo(fetchMock, "GET", STATUS).length;
    await userEvent.click(cancelButtons()[1]);
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", CANCEL(OTHER_JOB))).toHaveLength(1));
    expect(callsTo(fetchMock, "POST", CANCEL(ids.job))).toHaveLength(0);
    await waitFor(() => expect(callsTo(fetchMock, "GET", STATUS).length).toBeGreaterThan(statusCalls));
  });

  it("while cancelling shows Cancelling… and disables the buttons", async () => {
    let release: (r: Response) => void = () => {};
    mockApi(
      {
        [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])),
        [`POST ${CANCEL(ids.job)}`]: () => new Promise<Response>((resolve) => (release = resolve)),
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    expect(await screen.findByText("Cancelling…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Keep going" })).toBeDisabled();
    release(respond(200, makeJob({ status: "cancelled" })));
  });

  it.each([
    ["tender_archived", /This tender is archived, so nothing can be cancelled\./],
    ["job_not_cancellable", /This step cannot be cancelled\./],
  ])("explains the %s refusal in plain words", async (code, pattern) => {
    mockApi(
      {
        [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])),
        [`POST ${CANCEL(ids.job)}`]: () => respond(409, errorBody(code, "raw server text")),
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(pattern);
    expect(alert).not.toHaveTextContent("raw server text");
  });

  it("shows a plain message when the cancel cannot reach the server", async () => {
    mockApi(
      {
        [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", running(ids.job), null)])),
        [`POST ${CANCEL(ids.job)}`]: () => {
          throw new TypeError("Failed to fetch");
        },
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not cancel the extraction. Try again.");
  });

  it("after a cancel shows Cancelled, no progress bar, no Cancel, and lets the run start again", async () => {
    let cancelled = false;
    mockApi(
      {
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([
            makeKind(
              "boq",
              cancelled
                ? { status: "cancelled", progress_done: 3, progress_total: 9 }
                : { status: "running", progress_done: 3, progress_total: 9 },
              null,
            ),
          ])),
        [`POST ${CANCEL(ids.job)}`]: () => {
          cancelled = true;
          return respond(200, makeJob({ status: "cancelled" }));
        },
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(cancelButtons()).toHaveLength(0);
    expect(screen.getByRole("button", { name: /run extraction again/i })).toBeEnabled();
  });
});
