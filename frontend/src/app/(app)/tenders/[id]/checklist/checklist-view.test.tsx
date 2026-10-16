import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { REVIEW_PAGE_SIZE } from "@/api/review";
import { ids, makeDocument, makeRequirement, makeTender } from "@/test/fixtures";
import { callsTo, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: ids.tender }),
}));

import { ChecklistView } from "./checklist-view";

afterEach(() => vi.unstubAllGlobals());

const LIST = `/api/v1/tenders/${ids.tender}/requirements`;
const me = meWith(["read"], "reviewer");

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
    expect(within(group).getByRole("link", { name: "Open in review" })).toHaveAttribute(
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
    expect(screen.getByText(/loaded requirements only/)).toBeInTheDocument();
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
});
