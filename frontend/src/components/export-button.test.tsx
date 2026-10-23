import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import { ExportButton } from "./export-button";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const TENDER = "00000000-0000-4000-8000-000000000100";
const EXP = "00000000-0000-4000-8000-000000000999";
const PATH = `/api/v1/tenders/${TENDER}/exports`;
const allowed = meWith(["read", "export"]);

const dto = (label: "draft" | "reviewed" | "approved") => ({
  id: EXP,
  file_name: `estimate-v1-${label}.xlsx`,
  label,
  kind: "estimate_xlsx",
});

function setup(
  handler: () => Response | Promise<Response>,
  props: Partial<React.ComponentProps<typeof ExportButton>> = {},
  me = allowed,
) {
  const fetchMock = mockApi({ [`POST ${PATH}`]: handler }, me);
  renderSignedIn(<ExportButton tenderId={TENDER} kind="estimate_xlsx" label="Download Excel" {...props} />);
  return fetchMock;
}

describe("ExportButton", () => {
  it("is hidden without the export permission", async () => {
    const fetchMock = setup(() => respond(201, dto("approved")), { draftNote: "A note" }, meWith(["read"]));
    await waitFor(() => expect(callsTo(fetchMock, "GET", "/api/v1/me")).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button", { name: "Download Excel" })).toBeNull();
  });

  it("shows the draft note before any click", async () => {
    setup(() => respond(201, dto("draft")), { draftNote: "This file will be marked DRAFT." });
    expect(await screen.findByText("This file will be marked DRAFT.")).toBeInTheDocument();
  });

  it("creates once even on a double click, shows Preparing file and disables", async () => {
    let release: (r: Response) => void = () => {};
    const pending = new Promise<Response>((r) => (release = r));
    const fetchMock = setup(() => pending, { estimateId: "e1" });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Download Excel" });
    await user.dblClick(button);
    const busy = await screen.findByRole("button", { name: "Preparing file" });
    expect(busy).toBeDisabled();
    expect(callsTo(fetchMock, "POST", PATH)).toHaveLength(1);
    expect(JSON.parse((callsTo(fetchMock, "POST", PATH)[0][1] as RequestInit).body as string)).toEqual({
      kind: "estimate_xlsx",
      estimate_id: "e1",
    });
    release(respond(201, dto("approved")));
    await screen.findByText(/Downloaded/);
  });

  it("downloads on success and offers the same link", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.getAttribute("href")).toBe(`/api/v1/exports/${EXP}/download`);
      expect(this.download).toBe("estimate-v1-approved.xlsx");
    });
    setup(() => respond(201, dto("approved")));
    await userEvent.setup().click(await screen.findByRole("button", { name: "Download Excel" }));
    const link = await screen.findByRole("link", { name: /estimate-v1-approved\.xlsx/ });
    expect(link).toHaveAttribute("href", `/api/v1/exports/${EXP}/download`);
    expect(link).toHaveAttribute("download", "estimate-v1-approved.xlsx");
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/DRAFT/)).toBeNull();
  });

  it("marks a non-approved result as DRAFT", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    setup(() => respond(201, dto("reviewed")));
    await userEvent.setup().click(await screen.findByRole("button", { name: "Download Excel" }));
    expect(await screen.findByText(/\(marked DRAFT\)/)).toBeInTheDocument();
  });

  it("follows the server label, not draftNote, after success", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    setup(() => respond(201, dto("approved")), { draftNote: "This file will be marked DRAFT." });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Download Excel" }));
    await screen.findByText(/Downloaded/);
    expect(screen.queryByText(/marked DRAFT/)).toBeNull();
  });

  it("shows a plain sentence on no_estimate in an alert", async () => {
    setup(() => respond(409, errorBody("no_estimate", "raw server text")));
    await userEvent.setup().click(await screen.findByRole("button", { name: "Download Excel" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/no estimate/i);
    expect(alert).not.toHaveTextContent("no_estimate");
    expect(screen.getByRole("button", { name: "Download Excel" })).toBeEnabled();
  });
});
