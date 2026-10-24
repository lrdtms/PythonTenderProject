"use client";

import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import {
  type Member,
  membersQueryOptions,
  useChangeRole,
  useCreateMember,
  useResetPassword,
  useSetMemberStatus,
} from "@/api/members";
import type { Role } from "@/api/types";
import { useCan, useSession } from "@/components/auth-gate";
import { Field } from "@/components/field";
import { StatusBadge } from "@/components/status-badge";

const ROLES: { value: Role; label: string }[] = [
  { value: "admin", label: "Admin" },
  { value: "estimator", label: "Estimator" },
  { value: "project_manager", label: "Project manager" },
  { value: "reviewer", label: "Reviewer" },
];

const BUTTON = "rounded border px-2 py-1 text-sm disabled:opacity-50";

/** Server messages are already plain words; a 422 from the request schema carries
 * details: [{field, message}], shown with the field name. */
function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (Array.isArray(error.details)) {
      const messages = error.details
        .map((d) => {
          if (typeof d !== "object" || d === null) return null;
          const { field, message } = d as { field?: unknown; message?: unknown };
          if (typeof message !== "string") return null;
          return typeof field === "string" && field ? `${field}: ${message}` : message;
        })
        .filter((m): m is string => m !== null);
      if (messages.length > 0) return messages.join(" ");
    }
    return error.message;
  }
  return "Something went wrong. Try again.";
}

function CreateMember() {
  const create = useCreateMember();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("estimator");
  const [password, setPassword] = useState("");
  const [added, setAdded] = useState(false);

  // Editing a field clears the previous outcome, so a stale message never sits beside new input.
  const touch = () => {
    if (added) setAdded(false);
    if (create.isError) create.reset();
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending) return;
    setAdded(false);
    create.mutate(
      { name, email, role, password },
      {
        onSuccess: () => {
          setName("");
          setEmail("");
          setPassword("");
          setAdded(true);
        },
      },
    );
  }

  return (
    <details className="group mb-6">
      <summary className="btn btn-primary w-fit list-none group-open:mb-4 [&::-webkit-details-marker]:hidden">Add a member</summary>
    <form onSubmit={submit} className="panel space-y-3 p-4" aria-label="Add a member">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" required value={name} onChange={(e) => (touch(), setName(e.target.value))} />
        <Field label="Email" type="email" required autoComplete="off" value={email} onChange={(e) => (touch(), setEmail(e.target.value))} />
        <Field label="Temporary password" type="password" required autoComplete="new-password" value={password} onChange={(e) => (touch(), setPassword(e.target.value))} />
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Role</span>
          <select value={role} onChange={(e) => (touch(), setRole(e.target.value as Role))} className="input">
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-zinc-500">At least 10 characters. Share it with the person safely; they can be given a new one at any time.</p>
      {create.error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {errorText(create.error)}
        </p>
      ) : null}
      {added ? <p role="status" className="text-sm text-green-700 dark:text-green-300">Member added.</p> : null}
      <button type="submit" disabled={create.isPending} className="btn">
        {create.isPending ? "Adding…" : "Add member"}
      </button>
    </form>
    </details>
  );
}

type Outcome = { kind: "error" | "ok"; text: string } | null;

function MemberRow({ member, isSelf }: { member: Member; isSelf: boolean }) {
  const changeRole = useChangeRole();
  const setStatus = useSetMemberStatus();
  const reset = useResetPassword();
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [confirmingDeactivate, setConfirmingDeactivate] = useState(false);
  const [pendingRole, setPendingRole] = useState<Role | null>(null);
  const [resetting, setResetting] = useState(false);
  const [password, setPassword] = useState("");
  const deactivateRef = useRef<HTMLButtonElement>(null);
  const resetRef = useRef<HTMLButtonElement>(null);
  const active = member.status === "active";
  const busy = changeRole.isPending || setStatus.isPending || reset.isPending;
  const fail = (error: unknown) => setOutcome({ kind: "error", text: errorText(error) });

  const applyRole = (role: Role) => {
    setOutcome(null);
    setPendingRole(null);
    changeRole.mutate({ id: member.membership_id, role }, { onError: fail });
  };
  const closeReset = () => {
    setPassword("");
    setResetting(false);
    requestAnimationFrame(() => resetRef.current?.focus());
  };
  // Giving up your own admin role cannot be undone by you, so it needs a second step.
  const losesAdmin = (role: Role) => isSelf && member.role === "admin" && role !== "admin";

  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-48 grow">
          <p className="font-medium">
            {member.name}
            {isSelf ? <span className="ml-2 text-xs text-zinc-500">(you)</span> : null}
          </p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{member.email}</p>
        </div>
        <label className="text-sm">
          <span className="sr-only">Role for {member.name}</span>
          <select
            value={member.role}
            disabled={busy}
            onChange={(e) => {
              const role = e.target.value as Role;
              if (losesAdmin(role)) setPendingRole(role);
              else applyRole(role);
            }}
            className="input"
          >
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <StatusBadge tone={active ? "success" : "neutral"} label={active ? "Active" : "Deactivated"} />
        <div className="flex gap-2">
          {active ? (
            confirmingDeactivate ? (
              <>
                <button
                  type="button"
                  autoFocus
                  disabled={busy}
                  aria-label={`Confirm deactivate ${member.name}`}
                  onClick={() => {
                    setOutcome(null);
                    setStatus.mutate(
                      { id: member.membership_id, active: false },
                      { onError: fail, onSettled: () => setConfirmingDeactivate(false) },
                    );
                  }}
                  className={BUTTON}
                >
                  Confirm deactivate
                </button>
                <button
                  type="button"
                  aria-label={`Cancel deactivate ${member.name}`}
                  onClick={() => {
                    setConfirmingDeactivate(false);
                    requestAnimationFrame(() => deactivateRef.current?.focus());
                  }}
                  className={BUTTON}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                ref={deactivateRef}
                type="button"
                disabled={busy}
                aria-label={`Deactivate ${member.name}`}
                onClick={() => setConfirmingDeactivate(true)}
                className={BUTTON}
              >
                Deactivate
              </button>
            )
          ) : (
            <button
              type="button"
              disabled={busy}
              aria-label={`Reactivate ${member.name}`}
              onClick={() => {
                setOutcome(null);
                setStatus.mutate({ id: member.membership_id, active: true }, { onError: fail });
              }}
              className={BUTTON}
            >
              Reactivate
            </button>
          )}
          <button
            ref={resetRef}
            type="button"
            disabled={busy}
            aria-expanded={resetting}
            aria-label={`Reset password for ${member.name}`}
            onClick={() => (resetting ? closeReset() : setResetting(true))}
            className={BUTTON}
          >
            Reset password
          </button>
        </div>
      </div>
      {confirmingDeactivate && isSelf ? (
        <p className="text-sm text-amber-800 dark:text-amber-300">
          This is your own account. Deactivating it signs you out and you will not be able to sign in again until an admin reactivates it.
        </p>
      ) : null}
      {pendingRole ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <p className="text-amber-800 dark:text-amber-300">
            Change your own role to {ROLES.find((r) => r.value === pendingRole)?.label}? You will lose admin access and cannot undo this yourself.
          </p>
          <button type="button" autoFocus disabled={busy} onClick={() => applyRole(pendingRole)} className={BUTTON}>
            Change my role
          </button>
          <button type="button" onClick={() => setPendingRole(null)} className={BUTTON}>
            Keep admin
          </button>
        </div>
      ) : null}
      {resetting ? (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (busy) return;
            setOutcome(null);
            reset.mutate(
              { id: member.membership_id, password },
              {
                onSuccess: () => {
                  closeReset();
                  setOutcome({ kind: "ok", text: "Password changed and sessions ended." });
                },
                onError: fail,
              },
            );
          }}
        >
          <Field
            label={`New password for ${member.name}`}
            type="password"
            required
            autoFocus
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button type="submit" disabled={busy} className="btn">
            Set password
          </button>
          <p className="basis-full text-xs text-zinc-500">
            This signs {isSelf ? "you" : "them"} out everywhere. At least 10 characters.
          </p>
        </form>
      ) : null}
      {outcome ? (
        <p
          role={outcome.kind === "error" ? "alert" : "status"}
          className={`text-sm ${outcome.kind === "error" ? "text-red-700 dark:text-red-300" : "text-green-700 dark:text-green-300"}`}
        >
          {outcome.text}
        </p>
      ) : null}
    </li>
  );
}

export function MembersView() {
  const me = useSession();
  const canManage = useCan("manage_members");
  const members = useQuery({ ...membersQueryOptions, enabled: canManage });

  if (!canManage) {
    return (
      <div>
        <h1 className="mb-2 text-[22px] font-semibold leading-tight">Members</h1>
        <p>Only an admin can manage members.</p>
      </div>
    );
  }

  return (
    <section>
      <h1 className="mb-1 text-[22px] font-semibold leading-tight">Members</h1>
      <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
        People in {me.organisation_name}. An organisation always keeps at least one active admin.
      </p>
      <CreateMember />
      {members.isPending ? <p role="status" className="text-sm text-zinc-500">Loading members…</p> : null}
      {members.isError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Could not load the members.{" "}
          <button type="button" onClick={() => void members.refetch()} className="underline">
            Try again
          </button>
        </p>
      ) : null}
      {members.data ? (
        <ul aria-label="Members" className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {members.data.map((m) => (
            <MemberRow key={m.membership_id} member={m} isSelf={m.user_id === me.user_id} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
