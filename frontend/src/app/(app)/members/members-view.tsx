"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

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

/** Server messages are already plain words; a 422 may carry field messages in details. */
function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (Array.isArray(error.details)) {
      const messages = error.details
        .map((d) => (typeof d === "object" && d !== null ? (d as { message?: unknown }).message : null))
        .filter((m): m is string => typeof m === "string");
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

  function submit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending) return;
    create.mutate(
      { name, email, role, password },
      {
        onSuccess: () => {
          setName("");
          setEmail("");
          setPassword("");
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="mb-8 space-y-3 rounded border border-zinc-300 p-4 dark:border-zinc-700" aria-label="Add a member">
      <h2 className="text-lg font-medium">Add a member</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <Field label="Email" type="email" required autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="Temporary password" type="password" required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700">
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
      {create.isSuccess ? <p role="status" className="text-sm text-green-700 dark:text-green-300">Member added.</p> : null}
      <button type="submit" disabled={create.isPending} className="rounded border px-3 py-1 text-sm disabled:opacity-50">
        {create.isPending ? "Adding…" : "Add member"}
      </button>
    </form>
  );
}

function MemberRow({ member, isSelf }: { member: Member; isSelf: boolean }) {
  const changeRole = useChangeRole();
  const setStatus = useSetMemberStatus();
  const reset = useResetPassword();
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [password, setPassword] = useState("");
  const active = member.status === "active";
  const busy = changeRole.isPending || setStatus.isPending || reset.isPending;
  const error = changeRole.error ?? setStatus.error ?? reset.error;

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
            onChange={(e) => changeRole.mutate({ id: member.membership_id, role: e.target.value as Role })}
            className="rounded border bg-transparent p-1"
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
            confirming ? (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setStatus.mutate({ id: member.membership_id, active: false }, { onSettled: () => setConfirming(false) })}
                  className="rounded border px-2 py-1 text-sm disabled:opacity-50"
                >
                  Confirm deactivate
                </button>
                <button type="button" onClick={() => setConfirming(false)} className="rounded border px-2 py-1 text-sm">
                  Cancel
                </button>
              </>
            ) : (
              <button type="button" disabled={busy} onClick={() => setConfirming(true)} className="rounded border px-2 py-1 text-sm disabled:opacity-50">
                Deactivate
              </button>
            )
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => setStatus.mutate({ id: member.membership_id, active: true })}
              className="rounded border px-2 py-1 text-sm disabled:opacity-50"
            >
              Reactivate
            </button>
          )}
          <button type="button" disabled={busy} onClick={() => setResetting((v) => !v)} className="rounded border px-2 py-1 text-sm disabled:opacity-50">
            Reset password
          </button>
        </div>
      </div>
      {resetting ? (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (busy) return;
            reset.mutate(
              { id: member.membership_id, password },
              {
                onSuccess: () => {
                  setPassword("");
                  setResetting(false);
                },
              },
            );
          }}
        >
          <Field label={`New password for ${member.name}`} type="password" required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <button type="submit" disabled={busy} className="rounded border px-3 py-2 text-sm disabled:opacity-50">
            Set password
          </button>
          <p className="basis-full text-xs text-zinc-500">
            This signs {isSelf ? "you" : "them"} out everywhere. At least 10 characters.
          </p>
        </form>
      ) : null}
      {reset.isSuccess && !resetting ? (
        <p role="status" className="text-sm text-green-700 dark:text-green-300">
          Password changed and sessions ended.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {errorText(error)}
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
      <div role="alert">
        <h1 className="mb-2 text-2xl font-semibold tracking-tight">Members</h1>
        <p>Only an admin can manage members.</p>
      </div>
    );
  }

  return (
    <section>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Members</h1>
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
