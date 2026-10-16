import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Member } from "@/api/members";
import { ME, callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import { MembersView } from "./members-view";

afterEach(() => vi.unstubAllGlobals());

const admin = meWith(["read", "manage_members"], "admin");
const member = (over: Partial<Member>): Member => ({
  membership_id: "m1",
  user_id: "u1",
  name: "Sam Estimator",
  email: "sam@example.com",
  role: "estimator",
  status: "active",
  ...over,
});
const SELF = member({ membership_id: "m0", user_id: ME.user_id, name: ME.name, email: ME.email, role: "admin" });

const bodyOf = (call: unknown[]) => JSON.parse((call[1] as RequestInit).body as string);

describe("MembersView", () => {
  it("tells a non-admin they have no access and never asks for the list", async () => {
    const fetchMock = mockApi({}, meWith(["read"], "estimator"));
    renderSignedIn(<MembersView />);
    expect(await screen.findByText("Only an admin can manage members.")).toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "/api/v1/members")).toHaveLength(0);
  });

  it("lists members, marks the current user, and shows deactivated status in words", async () => {
    mockApi({ "GET /api/v1/members": () => respond(200, [SELF, member({ status: "deactivated" })]) }, admin);
    renderSignedIn(<MembersView />);
    expect(await screen.findByText("Sam Estimator")).toBeInTheDocument();
    expect(screen.getByText("(you)")).toBeInTheDocument();
    expect(screen.getByText("Deactivated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reactivate Sam Estimator" })).toBeInTheDocument();
  });

  it("creates a member and clears the form", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF]),
        "POST /api/v1/members": () => respond(201, member({})),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    await screen.findByText("(you)");
    await userEvent.type(screen.getByLabelText("Name"), "Sam Estimator");
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Temporary password"), "long-enough-pass");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "reviewer");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/members")).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "POST", "/api/v1/members")[0])).toEqual({
      name: "Sam Estimator", email: "sam@example.com", role: "reviewer", password: "long-enough-pass",
    });
    expect(await screen.findByText("Member added.")).toBeInTheDocument();
    expect(screen.getByLabelText("Temporary password")).toHaveValue("");
  });

  it("shows the server's message when the email is taken, keeping what was typed", async () => {
    mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF]),
        "POST /api/v1/members": () => respond(409, errorBody("conflict", "An account with this email already exists.")),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    await screen.findByText("(you)");
    await userEvent.type(screen.getByLabelText("Name"), "Sam");
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Temporary password"), "long-enough-pass");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    expect(await screen.findByText("An account with this email already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("sam@example.com");
  });

  it("changes a role and reloads the list; the last-admin refusal is shown and the old role returns", async () => {
    let calls = 0;
    let lists = 0;
    const fetchMock = mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({ role: lists++ === 0 ? "estimator" : "reviewer" })]),
        "PATCH /api/v1/members/m1/role": () => {
          calls += 1;
          return respond(422, errorBody("validation_error", "An organisation needs at least one active admin."));
        },
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    await screen.findByText("(you)");
    await userEvent.selectOptions(screen.getByLabelText("Role for Sam Estimator"), "admin");
    expect(await screen.findByText("An organisation needs at least one active admin.")).toBeInTheDocument();
    expect(calls).toBe(1);
    expect(bodyOf(callsTo(fetchMock, "PATCH", "/api/v1/members/m1/role")[0])).toEqual({ role: "admin" });
    // The list is re-read after the failure: the second GET returns the role the server really has.
    await waitFor(() => expect(screen.getByLabelText("Role for Sam Estimator")).toHaveValue("reviewer"));
  });

  it("deactivates only after a second click, without a native dialog", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({})]),
        "POST /api/v1/members/m1/deactivate": () => respond(200, member({ status: "deactivated" })),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    const row = (await screen.findByText("Sam Estimator")).closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Deactivate Sam Estimator" }));
    expect(callsTo(fetchMock, "POST", "/api/v1/members/m1/deactivate")).toHaveLength(0);
    await userEvent.click(within(row).getByRole("button", { name: "Confirm deactivate Sam Estimator" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/members/m1/deactivate")).toHaveLength(1));
  });

  it("resets a password and says sessions ended; the password is not kept", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({})]),
        "POST /api/v1/members/m1/reset-password": () => new Response(null, { status: 204 }),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    const row = (await screen.findByText("Sam Estimator")).closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Reset password for Sam Estimator" }));
    await userEvent.type(within(row).getByLabelText("New password for Sam Estimator"), "another-long-pass");
    await userEvent.click(within(row).getByRole("button", { name: "Set password" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/members/m1/reset-password")).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "POST", "/api/v1/members/m1/reset-password")[0])).toEqual({ password: "another-long-pass" });
    expect(await within(row).findByText(/Password changed and sessions ended/)).toBeInTheDocument();
    expect(within(row).queryByLabelText("New password for Sam Estimator")).toBeNull();
  });

  it("shows a password-policy message from a 422 detail", async () => {
    mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({})]),
        "POST /api/v1/members/m1/reset-password": () =>
          respond(422, { error: { code: "validation_error", message: "Use at least 10 characters.", details: { field: "password" } } }),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    const row = (await screen.findByText("Sam Estimator")).closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Reset password for Sam Estimator" }));
    await userEvent.type(within(row).getByLabelText("New password for Sam Estimator"), "short");
    await userEvent.click(within(row).getByRole("button", { name: "Set password" }));
    expect(await within(row).findByText("Use at least 10 characters.")).toBeInTheDocument();
  });

  it("asks before you give up your own admin role, and Keep admin sends nothing", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({ role: "admin", membership_id: "m2", user_id: "u2", name: "Other Admin" })]),
        "PATCH /api/v1/members/m0/role": () => respond(200, { ...SELF, role: "estimator" }),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    await screen.findByText("Other Admin");
    await userEvent.selectOptions(screen.getByLabelText(`Role for ${ME.name}`), "estimator");
    expect(screen.getByText(/You will lose admin access/)).toBeInTheDocument();
    expect(callsTo(fetchMock, "PATCH", "/api/v1/members/m0/role")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Keep admin" }));
    expect(screen.queryByText(/You will lose admin access/)).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText(`Role for ${ME.name}`), "estimator");
    await userEvent.click(screen.getByRole("button", { name: "Change my role" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", "/api/v1/members/m0/role")).toHaveLength(1));
  });

  it("re-reads who you are after a role change, so a demoted admin loses the page", async () => {
    let meCalls = 0;
    mockApi(
      {
        "GET /api/v1/me": () => respond(200, meCalls++ === 0 ? admin : meWith(["read"], "estimator")),
        "GET /api/v1/members": () => respond(200, [SELF, member({ role: "admin", membership_id: "m2", user_id: "u2", name: "Other Admin" })]),
        "PATCH /api/v1/members/m0/role": () => respond(200, { ...SELF, role: "estimator" }),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    await screen.findByText("Other Admin");
    await userEvent.selectOptions(screen.getByLabelText(`Role for ${ME.name}`), "estimator");
    await userEvent.click(screen.getByRole("button", { name: "Change my role" }));
    expect(await screen.findByText("Only an admin can manage members.")).toBeInTheDocument();
  });

  it("warns on your own deactivate confirm", async () => {
    mockApi({ "GET /api/v1/members": () => respond(200, [SELF, member({ role: "admin", membership_id: "m2", user_id: "u2", name: "Other Admin" })]) }, admin);
    renderSignedIn(<MembersView />);
    await screen.findByText("Other Admin");
    await userEvent.click(screen.getByRole("button", { name: `Deactivate ${ME.name}` }));
    expect(screen.getByText(/signs you out/)).toBeInTheDocument();
  });

  it("does not keep a stale error after a later action succeeds", async () => {
    let fail = true;
    mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({})]),
        "PATCH /api/v1/members/m1/role": () => (fail ? respond(422, errorBody("validation_error", "Nope.")) : respond(200, member({ role: "reviewer" }))),
        "POST /api/v1/members/m1/deactivate": () => respond(200, member({ status: "deactivated" })),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    const row = (await screen.findByText("Sam Estimator")).closest("li") as HTMLElement;
    await userEvent.selectOptions(within(row).getByLabelText("Role for Sam Estimator"), "reviewer");
    expect(await within(row).findByText("Nope.")).toBeInTheDocument();
    fail = false;
    await userEvent.click(within(row).getByRole("button", { name: "Deactivate Sam Estimator" }));
    await userEvent.click(within(row).getByRole("button", { name: "Confirm deactivate Sam Estimator" }));
    await waitFor(() => expect(within(row).queryByText("Nope.")).toBeNull());
  });

  it("forgets the typed password when the reset form is closed and reopened", async () => {
    mockApi({ "GET /api/v1/members": () => respond(200, [SELF, member({})]) }, admin);
    renderSignedIn(<MembersView />);
    const row = (await screen.findByText("Sam Estimator")).closest("li") as HTMLElement;
    const toggle = within(row).getByRole("button", { name: "Reset password for Sam Estimator" });
    await userEvent.click(toggle);
    await userEvent.type(within(row).getByLabelText("New password for Sam Estimator"), "secret-typed-pass");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(within(row).getByLabelText("New password for Sam Estimator")).toHaveValue("");
  });

  it("clears 'Member added.' as soon as the form is edited", async () => {
    mockApi({ "GET /api/v1/members": () => respond(200, [SELF]), "POST /api/v1/members": () => respond(201, member({})) }, admin);
    renderSignedIn(<MembersView />);
    await screen.findByText("(you)");
    await userEvent.type(screen.getByLabelText("Name"), "Sam");
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Temporary password"), "long-enough-pass");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    expect(await screen.findByText("Member added.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), "x");
    expect(screen.queryByText("Member added.")).toBeNull();
  });

  it("reactivates a deactivated member", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/members": () => respond(200, [SELF, member({ status: "deactivated" })]),
        "POST /api/v1/members/m1/reactivate": () => respond(200, member({})),
      },
      admin,
    );
    renderSignedIn(<MembersView />);
    await userEvent.click(await screen.findByRole("button", { name: "Reactivate Sam Estimator" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", "/api/v1/members/m1/reactivate")).toHaveLength(1));
  });
});
