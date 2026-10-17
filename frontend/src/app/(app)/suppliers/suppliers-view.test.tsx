import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeSupplier } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import { SuppliersView } from "./suppliers-view";

afterEach(() => vi.unstubAllGlobals());

const estimator = meWith(["read", "review_data"], "estimator");
const reviewer = meWith(["read"], "reviewer");

const A = makeSupplier({ id: "a", name: "Bright Sparks", notes: "Prefers email", quotation_count: 1 });
const B = makeSupplier({ id: "b", name: "Volt Co", notes: null, quotation_count: 3 });
const LIST = [A, B];

const bodyOf = (call: unknown[]) => JSON.parse((call[1] as RequestInit).body as string);

describe("SuppliersView", () => {
  it("lists suppliers with quotation counts in words and notes", async () => {
    mockApi({ "GET /api/v1/suppliers": () => respond(200, LIST) }, estimator);
    renderSignedIn(<SuppliersView />);
    await screen.findByRole("list", { name: "Suppliers" });
    expect(screen.getByText("1 quotation")).toBeInTheDocument();
    expect(screen.getByText("3 quotations")).toBeInTheDocument();
    expect(screen.getByText("Prefers email")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mockApi({ "GET /api/v1/suppliers": () => respond(200, []) }, estimator);
    renderSignedIn(<SuppliersView />);
    expect(
      await screen.findByText("No suppliers yet. They appear when you upload a quotation."),
    ).toBeInTheDocument();
  });

  it("shows an error with a retry when the list fails", async () => {
    mockApi({ "GET /api/v1/suppliers": () => respond(500, errorBody("internal_error", "Oops.")) }, estimator);
    renderSignedIn(<SuppliersView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the suppliers.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("gives a reviewer the list and no controls", async () => {
    mockApi({ "GET /api/v1/suppliers": () => respond(200, LIST) }, reviewer);
    renderSignedIn(<SuppliersView />);
    await screen.findByRole("list", { name: "Suppliers" });
    expect(screen.queryByRole("form", { name: "Add a supplier" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Edit / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Merge / })).toBeNull();
  });

  it("creates a supplier, omitting blank notes, and clears the form", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/suppliers": () => respond(200, LIST),
        "POST /api/v1/suppliers": () => respond(201, makeSupplier({ id: "c", name: "New Co" })),
      },
      estimator,
    );
    renderSignedIn(<SuppliersView />);
    await screen.findByRole("list", { name: "Suppliers" });
    await userEvent.type(screen.getByLabelText("Name"), "New Co");
    await userEvent.click(screen.getByRole("button", { name: "Add supplier" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/suppliers")).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "POST", "/api/v1/suppliers")[0])).toEqual({ name: "New Co" });
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue(""));
  });

  it("sends notes on create when given", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/suppliers": () => respond(200, LIST),
        "POST /api/v1/suppliers": () => respond(201, makeSupplier({ id: "c" })),
      },
      estimator,
    );
    renderSignedIn(<SuppliersView />);
    await screen.findByRole("list", { name: "Suppliers" });
    await userEvent.type(screen.getByLabelText("Name"), "New Co");
    await userEvent.type(screen.getByLabelText("Notes"), "Cables");
    await userEvent.click(screen.getByRole("button", { name: "Add supplier" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/suppliers")).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "POST", "/api/v1/suppliers")[0])).toEqual({ name: "New Co", notes: "Cables" });
  });

  it("shows the duplicate message on create and keeps the typed name", async () => {
    mockApi(
      {
        "GET /api/v1/suppliers": () => respond(200, LIST),
        "POST /api/v1/suppliers": () => respond(409, errorBody("supplier_exists", "dup")),
      },
      estimator,
    );
    renderSignedIn(<SuppliersView />);
    await screen.findByRole("list", { name: "Suppliers" });
    await userEvent.type(screen.getByLabelText("Name"), "Volt Co");
    await userEvent.click(screen.getByRole("button", { name: "Add supplier" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A supplier with this name already exists. Merge them instead.",
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Volt Co");
  });

  it("refuses a whitespace-only name on create without sending a request", async () => {
    const fetchMock = mockApi({ "GET /api/v1/suppliers": () => respond(200, LIST) }, estimator);
    renderSignedIn(<SuppliersView />);
    await screen.findByRole("list", { name: "Suppliers" });
    await userEvent.type(screen.getByLabelText("Name"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "Add supplier" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a name.");
    expect(callsTo(fetchMock, "POST", "/api/v1/suppliers")).toHaveLength(0);
  });

  describe("edit", () => {
    async function openEditor(fetchMock?: unknown) {
      void fetchMock;
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.click(screen.getByRole("button", { name: "Edit Bright Sparks" }));
    }
    const routes = (patch: () => Response) => ({
      "GET /api/v1/suppliers": () => respond(200, LIST),
      "PATCH /api/v1/suppliers/a": patch,
    });

    it("sends only the name when only the name changed", async () => {
      const fetchMock = mockApi(routes(() => respond(200, A)), estimator);
      renderSignedIn(<SuppliersView />);
      await openEditor();
      const name = screen.getByLabelText("Name for Bright Sparks");
      await userEvent.clear(name);
      await userEvent.type(name, "Bright Sparks Ltd");
      await userEvent.click(screen.getByRole("button", { name: "Save Bright Sparks" }));
      await waitFor(() => expect(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")).toHaveLength(1));
      expect(bodyOf(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")[0])).toEqual({ name: "Bright Sparks Ltd" });
    });

    it("sends only the notes when only the notes changed", async () => {
      const fetchMock = mockApi(routes(() => respond(200, A)), estimator);
      renderSignedIn(<SuppliersView />);
      await openEditor();
      const notes = screen.getByLabelText("Notes for Bright Sparks");
      await userEvent.clear(notes);
      await userEvent.type(notes, "Phone only");
      await userEvent.click(screen.getByRole("button", { name: "Save Bright Sparks" }));
      await waitFor(() => expect(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")).toHaveLength(1));
      expect(bodyOf(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")[0])).toEqual({ notes: "Phone only" });
    });

    it("sends null when the notes are cleared", async () => {
      const fetchMock = mockApi(routes(() => respond(200, A)), estimator);
      renderSignedIn(<SuppliersView />);
      await openEditor();
      await userEvent.clear(screen.getByLabelText("Notes for Bright Sparks"));
      await userEvent.click(screen.getByRole("button", { name: "Save Bright Sparks" }));
      await waitFor(() => expect(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")).toHaveLength(1));
      expect(bodyOf(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")[0])).toEqual({ notes: null });
    });

    it("keeps the editor open with the typed value on a rename conflict", async () => {
      mockApi(routes(() => respond(409, errorBody("supplier_exists", "dup"))), estimator);
      renderSignedIn(<SuppliersView />);
      await openEditor();
      const name = screen.getByLabelText("Name for Bright Sparks");
      await userEvent.clear(name);
      await userEvent.type(name, "Volt Co");
      await userEvent.click(screen.getByRole("button", { name: "Save Bright Sparks" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "A supplier with this name already exists. Merge them instead.",
      );
      expect(screen.getByLabelText("Name for Bright Sparks")).toHaveValue("Volt Co");
    });

    it("refuses a whitespace-only name on rename without sending a request", async () => {
      const fetchMock = mockApi(routes(() => respond(200, A)), estimator);
      renderSignedIn(<SuppliersView />);
      await openEditor();
      const name = screen.getByLabelText("Name for Bright Sparks");
      await userEvent.clear(name);
      await userEvent.type(name, "   ");
      await userEvent.click(screen.getByRole("button", { name: "Save Bright Sparks" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Enter a name.");
      expect(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")).toHaveLength(0);
    });

    it("cancels without sending anything", async () => {
      const fetchMock = mockApi(routes(() => respond(200, A)), estimator);
      renderSignedIn(<SuppliersView />);
      await openEditor();
      await userEvent.click(screen.getByRole("button", { name: "Cancel edit Bright Sparks" }));
      expect(screen.queryByLabelText("Name for Bright Sparks")).toBeNull();
      expect(callsTo(fetchMock, "PATCH", "/api/v1/suppliers/a")).toHaveLength(0);
    });
  });

  describe("merge", () => {
    const routes = (merge: () => Response) => ({
      "GET /api/v1/suppliers": () => respond(200, [A, B, makeSupplier({ id: "c", name: "Zed Ltd" })]),
      "POST /api/v1/suppliers/a/merge": merge,
    });

    it("offers only the other suppliers and disables Merge until one is chosen", async () => {
      mockApi(routes(() => respond(200, B)), estimator);
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      const select = screen.getByLabelText("Merge Bright Sparks into");
      const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
      expect(options).not.toContain("Bright Sparks");
      expect(options).toEqual(expect.arrayContaining(["Volt Co", "Zed Ltd"]));
      expect(screen.getByRole("button", { name: "Merge Bright Sparks into…" })).toBeDisabled();
      await userEvent.selectOptions(select, "b");
      expect(screen.getByRole("button", { name: "Merge Bright Sparks into…" })).toBeEnabled();
    });

    it("asks for confirmation naming both suppliers, and Cancel sends nothing", async () => {
      const fetchMock = mockApi(routes(() => respond(200, B)), estimator);
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      expect(
        screen.getByText(
          "Merge Bright Sparks into Volt Co? Bright Sparks will disappear and its quotations move to Volt Co.",
        ),
      ).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Cancel merge Bright Sparks" }));
      expect(screen.queryByText(/will disappear/)).toBeNull();
      expect(callsTo(fetchMock, "POST", "/api/v1/suppliers/a/merge")).toHaveLength(0);
    });

    it("confirming posts into_id once and reports the merge", async () => {
      const fetchMock = mockApi(routes(() => respond(200, B)), estimator);
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      await userEvent.click(screen.getByRole("button", { name: "Confirm merge Bright Sparks" }));
      expect(await screen.findByText("Merged Bright Sparks into Volt Co.")).toBeInTheDocument();
      expect(callsTo(fetchMock, "POST", "/api/v1/suppliers/a/merge")).toHaveLength(1);
      expect(bodyOf(callsTo(fetchMock, "POST", "/api/v1/suppliers/a/merge")[0])).toEqual({ into_id: "b" });
    });

    it("shows the match_conflict text when the merge is refused", async () => {
      mockApi(routes(() => respond(409, errorBody("match_conflict", "x"))), estimator);
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      await userEvent.click(screen.getByRole("button", { name: "Confirm merge Bright Sparks" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "These suppliers both have a confirmed match for the same line. Resolve that first.",
      );
    });

    it("removes the source row, updates the target count and keeps the message after the row unmounts", async () => {
      let merged = false;
      const fetchMock = mockApi(
        {
          "GET /api/v1/suppliers": () => respond(200, merged ? [{ ...B, quotation_count: 4 }] : [A, B]),
          "POST /api/v1/suppliers/a/merge": () => {
            merged = true;
            return respond(200, B);
          },
        },
        estimator,
      );
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      await userEvent.click(screen.getByRole("button", { name: "Confirm merge Bright Sparks" }));
      expect(await screen.findByText("4 quotations")).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByText("Bright Sparks")).toBeNull());
      expect(screen.getByText("Merged Bright Sparks into Volt Co.")).toBeInTheDocument();
      expect(callsTo(fetchMock, "POST", "/api/v1/suppliers/a/merge")).toHaveLength(1);
    });

    it("sends one POST on a double click of Merge", async () => {
      const fetchMock = mockApi(
        routes(() => respond(200, B)),
        estimator,
      );
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      await userEvent.dblClick(screen.getByRole("button", { name: "Confirm merge Bright Sparks" }));
      await screen.findByText("Merged Bright Sparks into Volt Co.");
      expect(callsTo(fetchMock, "POST", "/api/v1/suppliers/a/merge")).toHaveLength(1);
    });

    it("says the supplier no longer exists on a 404 and reloads the list", async () => {
      const fetchMock = mockApi(routes(() => respond(404, errorBody("not_found", "Not found"))), estimator);
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      await userEvent.click(screen.getByRole("button", { name: "Confirm merge Bright Sparks" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("This supplier no longer exists. The list was reloaded.");
      await waitFor(() => expect(callsTo(fetchMock, "GET", "/api/v1/suppliers").length).toBeGreaterThan(1));
    });

    it("clears the merged banner when another action starts", async () => {
      mockApi({ ...routes(() => respond(200, B)), "PATCH /api/v1/suppliers/b": () => respond(200, B) }, estimator);
      renderSignedIn(<SuppliersView />);
      await screen.findByRole("list", { name: "Suppliers" });
      await userEvent.selectOptions(screen.getByLabelText("Merge Bright Sparks into"), "b");
      await userEvent.click(screen.getByRole("button", { name: "Merge Bright Sparks into…" }));
      await userEvent.click(screen.getByRole("button", { name: "Confirm merge Bright Sparks" }));
      await screen.findByText("Merged Bright Sparks into Volt Co.", {}, { timeout: 4000 });
      await userEvent.click(screen.getByRole("button", { name: "Edit Volt Co" }));
      expect(screen.queryByText("Merged Bright Sparks into Volt Co.")).toBeNull();
    });
  });
});
