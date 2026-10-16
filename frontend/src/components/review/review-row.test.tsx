import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeBoqItem, makeRequirement } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { BoqRow } from "./boq-row";
import { RequirementRow } from "./requirement-row";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const estimator = meWith(["read", "review_data"]);
const reviewer = meWith(["read"], "reviewer");
const noop = () => {};

function renderBoq(over = {}, archived = false) {
  const row = makeBoqItem({ id: "b1", ...over });
  return renderSignedIn(
    <ul>
      <BoqRow row={row} versionId={ids.version} selected onSelect={noop} archived={archived} />
    </ul>,
  );
}

describe("review rows", () => {
  it("shows state and chips to a reviewer but no controls", async () => {
    mockApi({}, reviewer);
    renderBoq({ flags: ["missing_quantity"] });
    expect(await screen.findByText("Unreviewed")).toBeInTheDocument();
    expect(screen.getByText("Quantity missing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("hides controls on an archived tender", async () => {
    mockApi({}, estimator);
    renderBoq({}, true);
    await screen.findByText("Unreviewed");
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("confirms a BoQ line", async () => {
    const fetchMock = mockApi({
      "POST /api/v1/boq-items/b1/confirm": () => respond(200, makeBoqItem({ id: "b1", review_status: "confirmed" })),
    });
    renderBoq();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/boq-items/b1/confirm")).toHaveLength(1));
  });

  it("rejects a requirement", async () => {
    const fetchMock = mockApi({
      "POST /api/v1/requirements/q1/reject": () => respond(200, makeRequirement({ id: "q1", review_status: "rejected" })),
    });
    renderSignedIn(
      <ul>
        <RequirementRow row={makeRequirement({ id: "q1" })} versionId={ids.version} selected onSelect={noop} />
      </ul>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/requirements/q1/reject")).toHaveLength(1));
  });

  it("rejects a bad quantity without sending, then sends only the changed field", async () => {
    const fetchMock = mockApi({
      "PATCH /api/v1/boq-items/b1": () => respond(200, makeBoqItem({ id: "b1", review_status: "corrected", quantity: "1500.0000" })),
    });
    renderBoq();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const qty = screen.getByLabelText("Quantity");
    await userEvent.clear(qty);
    await userEvent.type(qty, "1,500");
    expect(screen.getByRole("alert")).toHaveTextContent(/plain number/);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(qty);
    await userEvent.type(qty, "1500");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", "/api/v1/boq-items/b1")).toHaveLength(1));
    const body = JSON.parse((callsTo(fetchMock, "PATCH", "/api/v1/boq-items/b1")[0][1] as RequestInit).body as string);
    expect(body).toEqual({ quantity: "1500" });
  });

  it("clearing the quantity sends null", async () => {
    const fetchMock = mockApi({
      "PATCH /api/v1/boq-items/b1": () => respond(200, makeBoqItem({ id: "b1", review_status: "corrected", quantity: null })),
    });
    renderBoq();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.clear(screen.getByLabelText("Quantity"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", "/api/v1/boq-items/b1")).toHaveLength(1));
    const body = JSON.parse((callsTo(fetchMock, "PATCH", "/api/v1/boq-items/b1")[0][1] as RequestInit).body as string);
    expect(body).toEqual({ quantity: null });
  });

  it("offers only the enum values when editing a requirement", async () => {
    mockApi({});
    renderSignedIn(
      <ul>
        <RequirementRow row={makeRequirement({ id: "q1" })} versionId={ids.version} selected onSelect={noop} />
      </ul>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const options = screen.getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(options).toEqual([
      "deadline", "meeting", "eligibility", "document", "pricing", "technical", "other",
      "mandatory", "conditional", "informational",
    ]);
  });

  it("marks a row replaced by a re-run on 404", async () => {
    mockApi({ "POST /api/v1/boq-items/b1/confirm": () => respond(404, errorBody("not_found", "gone")) });
    renderBoq();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Replaced by a re-run/);
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("shows a permission message on 403 and restores the state", async () => {
    mockApi({ "POST /api/v1/boq-items/b1/confirm": () => respond(403, errorBody("forbidden", "no")) });
    renderBoq();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/permission/);
    expect(screen.getByText("Unreviewed")).toBeInTheDocument();
  });
});

