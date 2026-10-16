import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeBoqItem, makePageDetail, makeRequirement, makeTender, makeVersion } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: ids.tender, versionId: ids.version }),
}));
vi.mock("@/components/pdf/pdf-page", () => ({
  PdfPage: ({ pageNumber }: { pageNumber: number }) => <div data-testid="pdf">pdf page {pageNumber}</div>,
}));

import { REVIEW_PAGE_SIZE } from "@/api/review";

import { ReviewScreen } from "./review-screen";

afterEach(() => vi.unstubAllGlobals());

const V = ids.version;
const estimator = meWith(["read", "review_data"]);
const reviewer = meWith(["read"], "reviewer");

function routes(over: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    [`GET /api/v1/tenders/${ids.tender}`]: () => respond(200, makeTender()),
    [`GET /api/v1/document-versions/${V}`]: () => respond(200, makeVersion()),
    [`GET /api/v1/document-versions/${V}/requirements`]: () =>
      respond(200, [
        makeRequirement({ id: "q1", description: "First requirement", page_number: 1, quote_start: 10, quote_end: 53 }),
        makeRequirement({ id: "q2", description: "Second requirement", page_number: 2 }),
      ]),
    [`GET /api/v1/document-versions/${V}/boq-items`]: () => respond(200, [makeBoqItem({ id: "b1", description: "LED panel" })]),
    [`GET /api/v1/document-versions/${V}/pages/1`]: () => respond(200, makePageDetail({ text: "Preamble: must hold a valid tax clearance certificate." })),
    [`GET /api/v1/document-versions/${V}/pages/2`]: () => respond(200, makePageDetail({ page_number: 2, text: "Page two text" })),
    ...over,
  };
}

describe("ReviewScreen", () => {
  it("lists requirements, shows the source for the selected one, and switches to BoQ lines", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    expect(await screen.findByTestId("pdf")).toHaveTextContent("pdf page 1");
    expect(await screen.findByText("must hold a valid tax clearance certificate", { selector: "mark" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /BoQ lines/ }));
    expect(await screen.findByText("LED panel")).toBeInTheDocument();
  });

  it("moves the selection with the arrow keys", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("{ArrowDown}");
    await waitFor(() => expect(screen.getByTestId("pdf")).toHaveTextContent("pdf page 2"));
  });

  it("confirms the selected row with c for an estimator", async () => {
    const fetchMock = mockApi(
      routes({ "POST /api/v1/requirements/q1/confirm": () => respond(200, makeRequirement({ id: "q1", review_status: "confirmed" })) }),
      estimator,
    );
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("c");
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/requirements/q1/confirm")).toHaveLength(1));
  });

  it("ignores c for a reviewer and shows no controls", async () => {
    const fetchMock = mockApi(routes(), reviewer);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("c");
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.getByText(/can read this review but not change it/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("ignores shortcut keys typed into an input", async () => {
    const fetchMock = mockApi(routes(), estimator);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    await userEvent.type(screen.getByLabelText("Requirement text"), "cr");
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("offers Load more only after a full page", async () => {
    const full = Array.from({ length: REVIEW_PAGE_SIZE }, (_, i) => makeRequirement({ id: `q${i}`, description: `Req ${i}` }));
    const fetchMock = mockApi(routes({ [`GET /api/v1/document-versions/${V}/requirements`]: () => respond(200, full) }), estimator);
    renderSignedIn(<ReviewScreen />);
    const more = await screen.findByRole("button", { name: "Load more" });
    fetchMock.mockImplementationOnce(async () => respond(200, [makeRequirement({ id: "last", description: "Last one" })]));
    await userEvent.click(more);
    expect(await screen.findByText("Last one")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).toBeNull());
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("offset=200");
  });

  it("shows an archived tender read-only", async () => {
    mockApi(routes({ [`GET /api/v1/tenders/${ids.tender}`]: () => respond(200, makeTender({ status: "archived" })) }), estimator);
    renderSignedIn(<ReviewScreen />);
    await screen.findByText("First requirement");
    expect(screen.getByText(/archived and read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("shows an empty state", async () => {
    mockApi(
      routes({
        [`GET /api/v1/document-versions/${V}/requirements`]: () => respond(200, []),
        [`GET /api/v1/document-versions/${V}/boq-items`]: () => respond(200, []),
      }),
      estimator,
    );
    renderSignedIn(<ReviewScreen />);
    expect(await screen.findByText(/Nothing was extracted/)).toBeInTheDocument();
  });

  it("shows not found for an unknown version", async () => {
    mockApi(routes({ [`GET /api/v1/document-versions/${V}`]: () => respond(404, errorBody("not_found", "no")) }), estimator);
    renderSignedIn(<ReviewScreen />);
    expect(await screen.findByText("This document was not found.")).toBeInTheDocument();
  });

  it("shows a screen-level notice and reloads from offset 0 when a write finds its row replaced", async () => {
    const fetchMock = mockApi(
      routes({ "POST /api/v1/requirements/q1/confirm": () => respond(404, errorBody("not_found", "gone")) }),
      estimator,
    );
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("c");
    expect(await screen.findByText(/replaced by a re-run, so the list was reloaded/)).toBeInTheDocument();
    const list = `/api/v1/document-versions/${V}/requirements`;
    await waitFor(() => expect(callsTo(fetchMock, "GET", list).length).toBeGreaterThanOrEqual(2));
    expect(String(callsTo(fetchMock, "GET", list).at(-1)?.[0])).toContain("offset=0");
  });

  it("keeps an unsaved edit in the notice when its row was replaced", async () => {
    mockApi(routes({ "PATCH /api/v1/boq-items/b1": () => respond(404, errorBody("not_found", "gone")) }), estimator);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByRole("tab", { name: /BoQ lines/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const qty = screen.getByLabelText("Quantity");
    await userEvent.clear(qty);
    await userEvent.type(qty, "1500");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Your change was not saved: quantity 1500/)).toBeInTheDocument();
  });

  it("opens the editor only for the row the e key was pressed on", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("e");
    expect(await screen.findByLabelText("Requirement text")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByText("Second requirement"));
    expect(screen.queryByLabelText("Requirement text")).toBeNull();
  });

  it("keeps an open editor and its draft when another row is selected", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("e");
    await userEvent.type(await screen.findByLabelText("Requirement text"), " extra");
    await userEvent.click(screen.getByText("Second requirement"));
    expect(screen.getByLabelText("Requirement text")).toHaveValue("First requirement extra");
  });

  it("does not apply a confirm for one row to another that is selected later", async () => {
    const fetchMock = mockApi(
      routes({
        "POST /api/v1/requirements/q1/confirm": () => respond(200, makeRequirement({ id: "q1", review_status: "confirmed" })),
      }),
      estimator,
    );
    renderSignedIn(<ReviewScreen />);
    await userEvent.click(await screen.findByText("First requirement"));
    await userEvent.keyboard("c");
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/requirements/q1/confirm")).toHaveLength(1));
    await userEvent.keyboard("{ArrowDown}");
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(1);
  });

  it("opens on the BoQ tab when there are no requirements", async () => {
    mockApi(routes({ [`GET /api/v1/document-versions/${V}/requirements`]: () => respond(200, []) }), estimator);
    renderSignedIn(<ReviewScreen />);
    expect(await screen.findByText("LED panel")).toBeInTheDocument();
  });
});
