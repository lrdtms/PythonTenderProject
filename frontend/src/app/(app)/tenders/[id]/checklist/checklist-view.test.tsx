import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { REVIEW_PAGE_SIZE } from "@/api/review";
import { ids, makeDocument, makeRequirement, makeTender, makeVersion } from "@/test/fixtures";
import { callsTo, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: ids.tender }),
}));

import { ChecklistView } from "./checklist-view";

afterEach(() => vi.unstubAllGlobals());

const LIST = `/api/v1/tenders/${ids.tender}/requirements`;
const me = meWith(["read"], "reviewer");
const exporter = meWith(["read", "export"], "project_manager");

function routes(over: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    [`GET /api/v1/tenders/${ids.tender}`]: () => respond(200, makeTender()),
    [`GET /api/v1/tenders/${ids.tender}/documents`]: () => respond(200, [makeDocument({ title: "Tender pack" })]),
    [`GET ${LIST}`]: () =>
      respond(200, [
        makeRequirement({ id: "q1", description: "Hold a tax certificate", requirement_type: "eligibility", mandatory_status: "mandatory" }),
        makeRequirement({ id: "q2", description: "Attend the site meeting", requirement_type: "meeting", mandatory_status: "conditional", page_number: 4 }),
        makeRequirement({ id: "q3", description: "Submit by noon", requirement_type: "deadline", mandatory_status: "mandatory", review_status: "confirmed" }),
      ]),
    ...over,
  };
}

describe("ChecklistView", () => {
  it("groups requirements by type, names the document and links to the review row", async () => {
    mockApi(routes(), me);
    renderSignedIn(<ChecklistView />);
    const heading = await screen.findByRole("heading", { name: /Eligibility \(1\)/ });
    expect(heading).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Meeting \(1\)/ })).toBeInTheDocument();
    const group = heading.closest("section") as HTMLElement;
    expect(within(group).getByText(/Tender pack/)).toBeInTheDocument();
    expect(within(group).getByRole("link", { name: /Open in review: Hold a tax certificate/ })).toHaveAttribute(
      "href",
      `/tenders/${ids.tender}/review/${ids.version}?row=q1`,
    );
    expect(screen.getByText(/page 4/)).toBeInTheDocument();
  });

  it("falls back to 'Document' when the version is not in the document list", async () => {
    mockApi(routes({ [`GET /api/v1/tenders/${ids.tender}/documents`]: () => respond(200, []) }), me);
    renderSignedIn(<ChecklistView />);
    expect((await screen.findAllByText(/^Document/)).length).toBeGreaterThan(0);
  });

  it("narrows by mandatory status on the client without another request", async () => {
    const fetchMock = mockApi(routes(), me);
    renderSignedIn(<ChecklistView />);
    await screen.findByText("Hold a tax certificate");
    await userEvent.selectOptions(screen.getByLabelText("Mandatory status"), "conditional");
    expect(screen.queryByText("Hold a tax certificate")).toBeNull();
    expect(screen.getByText("Attend the site meeting")).toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", LIST)).toHaveLength(1);
  });

  it("asks the server for the review status filter, from offset 0", async () => {
    const fetchMock = mockApi(routes(), me);
    renderSignedIn(<ChecklistView />);
    await screen.findByText("Hold a tax certificate");
    await userEvent.selectOptions(screen.getByLabelText("Review status"), "confirmed");
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST)).toHaveLength(2));
    const last = String(callsTo(fetchMock, "GET", LIST).at(-1)?.[0]);
    expect(last).toContain("review_status=confirmed");
    expect(last).toContain("offset=0");
  });

  it("shows an empty state when nothing was extracted and when filters match nothing", async () => {
    mockApi(routes({ [`GET ${LIST}`]: () => respond(200, []) }), me);
    renderSignedIn(<ChecklistView />);
    expect(await screen.findByText(/No requirements have been extracted yet/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Type"), "pricing");
    expect(await screen.findByText(/No requirements match these filters/)).toBeInTheDocument();
  });

  it("offers Load more only after a full page, with a note while the mandatory filter is on", async () => {
    const full = Array.from({ length: REVIEW_PAGE_SIZE }, (_, i) => makeRequirement({ id: `r${i}`, description: `Req ${i}`, mandatory_status: "mandatory" }));
    const fetchMock = mockApi(routes({ [`GET ${LIST}`]: () => respond(200, full) }), me);
    renderSignedIn(<ChecklistView />);
    const more = await screen.findByRole("button", { name: "Load more" });
    await userEvent.selectOptions(screen.getByLabelText("Mandatory status"), "conditional");
    expect(screen.getByText(/Load more to check the rest/)).toBeInTheDocument();
    fetchMock.mockImplementationOnce(async () => respond(200, []));
    await userEvent.click(more);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).toBeNull());
    expect(String(callsTo(fetchMock, "GET", LIST).at(-1)?.[0])).toContain("offset=200");
  });

  it("says the tender was not found", async () => {
    mockApi(routes({ [`GET /api/v1/tenders/${ids.tender}`]: () => respond(404, { error: { code: "not_found", message: "no" } }) }), me);
    renderSignedIn(<ChecklistView />);
    expect(await screen.findByText("This tender was not found.")).toBeInTheDocument();
  });

  it("restarts from offset 0 and drops loaded pages when a filter changes after Load more", async () => {
    const full = Array.from({ length: REVIEW_PAGE_SIZE }, (_, i) => makeRequirement({ id: `r${i}`, description: `Req ${i}`, requirement_type: "pricing" }));
    const fetchMock = mockApi(routes({ [`GET ${LIST}`]: () => respond(200, full) }), me);
    renderSignedIn(<ChecklistView />);
    const more = await screen.findByRole("button", { name: "Load more" });
    fetchMock.mockImplementationOnce(async () => respond(200, [makeRequirement({ id: "page2", description: "Page two row", requirement_type: "pricing" })]));
    await userEvent.click(more);
    expect(await screen.findByText("Page two row")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Review status"), "confirmed");
    await waitFor(() => expect(screen.queryByText("Page two row")).toBeNull());
    expect(String(callsTo(fetchMock, "GET", LIST).at(-1)?.[0])).toMatch(/offset=0/);
  });

  it("says no documents have been uploaded, and that none has finished processing", async () => {
    mockApi(routes({ [`GET ${LIST}`]: () => respond(200, []), [`GET /api/v1/tenders/${ids.tender}/documents`]: () => respond(200, []) }), me);
    const first = renderSignedIn(<ChecklistView />);
    expect(await screen.findByText(/No documents have been uploaded yet/)).toBeInTheDocument();
    first.unmount();
    vi.unstubAllGlobals();
    mockApi(
      routes({
        [`GET ${LIST}`]: () => respond(200, []),
        [`GET /api/v1/tenders/${ids.tender}/documents`]: () => respond(200, [makeDocument({ current_version: makeVersion({ processing_status: "processing" }) })]),
      }),
      me,
    );
    renderSignedIn(<ChecklistView />);
    expect(await screen.findByText(/No document has finished processing yet/)).toBeInTheDocument();
  });

  describe("export button", () => {
    const unreviewed = (n: number) =>
      Array.from({ length: n }, (_, i) => makeRequirement({ id: `u${i}`, description: `Open ${i}`, review_status: "unreviewed" }));

    /** The page list answers `rest`; the separate unreviewed query (review_status=unreviewed, no type filter) answers `open`. */
    function setup(open: unknown[], rest: unknown[] = [makeRequirement({ id: "c1", description: "Done one", review_status: "confirmed" })], who = exporter) {
      const fetchMock = mockApi(routes({ [`GET ${LIST}`]: () => respond(200, rest) }), who);
      const base = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
        if (url.startsWith(LIST) && url.includes("review_status=unreviewed") && !url.includes("requirement_type")) return respond(200, open);
        return base(url, init);
      });
      return fetchMock;
    }

    it("is hidden without the export permission and does not ask for the unreviewed count", async () => {
      const fetchMock = setup(unreviewed(2), undefined, me);
      renderSignedIn(<ChecklistView />);
      await screen.findByText("Done one");
      expect(screen.queryByRole("button", { name: "Download PDF report" })).toBeNull();
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("review_status=unreviewed"))).toBe(false);
    });

    it("shows the button without a note when every requirement is reviewed", async () => {
      setup([]);
      renderSignedIn(<ChecklistView />);
      expect(await screen.findByRole("button", { name: "Download PDF report" })).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByText(/not reviewed yet/)).toBeNull());
    });

    it("warns that the report will be DRAFT when there are no non-rejected requirements", async () => {
      setup([], [makeRequirement({ id: "r1", description: "Dropped", review_status: "rejected" })]);
      renderSignedIn(<ChecklistView />);
      expect(await screen.findByText("No reviewed requirements yet. The report will be marked DRAFT.")).toBeInTheDocument();
    });

    it("shows the count of unreviewed requirements in the note", async () => {
      setup(unreviewed(3));
      renderSignedIn(<ChecklistView />);
      expect(
        await screen.findByText("3 requirements are not reviewed yet. The report will list them separately and be marked DRAFT."),
      ).toBeInTheDocument();
    });

    it("uses the singular for a single unreviewed requirement", async () => {
      setup(unreviewed(1));
      renderSignedIn(<ChecklistView />);
      expect(
        await screen.findByText("1 requirement is not reviewed yet. The report will list it separately and be marked DRAFT."),
      ).toBeInTheDocument();
    });

    it("warns that the report may be DRAFT when the unreviewed count cannot be loaded", async () => {
      const fetchMock = setup([]);
      const base = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
      fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
        if (url.startsWith(LIST) && url.includes("review_status=unreviewed") && !url.includes("requirement_type")) {
          return respond(500, { error: { code: "server_error", message: "Something went wrong." } });
        }
        return base(url, init);
      });
      renderSignedIn(<ChecklistView />);
      expect(
        await screen.findByText("The report may be marked DRAFT if requirements are not reviewed yet."),
      ).toBeInTheDocument();
    });

    it("says At least while the unreviewed query has another page", async () => {
      setup(unreviewed(REVIEW_PAGE_SIZE));
      renderSignedIn(<ChecklistView />);
      expect(
        await screen.findByText(`At least ${REVIEW_PAGE_SIZE} requirements are not reviewed yet. The report will list them separately and be marked DRAFT.`),
      ).toBeInTheDocument();
    });

    it("keeps the note when the Review status filter is Confirmed", async () => {
      const fetchMock = setup(unreviewed(2));
      renderSignedIn(<ChecklistView />);
      const note = "2 requirements are not reviewed yet. The report will list them separately and be marked DRAFT.";
      expect(await screen.findByText(note)).toBeInTheDocument();
      await userEvent.selectOptions(screen.getByLabelText("Review status"), "confirmed");
      await waitFor(() =>
        expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("review_status=confirmed"))).toBe(true),
      );
      await screen.findByText("Done one");
      expect(screen.getByText(note)).toBeInTheDocument();
    });
  });
});
