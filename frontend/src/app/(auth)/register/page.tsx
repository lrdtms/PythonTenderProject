"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { meQueryOptions, useRegister } from "@/api/session";
import { Field } from "@/components/field";

export default function RegisterPage() {
  const router = useRouter();
  const register = useRegister();
  const { data: me } = useQuery(meQueryOptions);
  const [organisationName, setOrganisationName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (me) router.replace("/tenders");
  }, [me, router]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (register.isPending) return;
    register.mutate(
      { organisation_name: organisationName, name, email, password },
      { onSuccess: () => router.replace("/tenders") },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <h2 className="text-xl font-medium">Create your organisation</h2>
      <Field label="Organisation name" required minLength={2} value={organisationName}
        onChange={(e) => setOrganisationName(e.target.value)} />
      <Field label="Your name" autoComplete="name" required value={name}
        onChange={(e) => setName(e.target.value)} />
      <Field label="Email" type="email" autoComplete="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="new-password" required
        value={password} onChange={(e) => setPassword(e.target.value)} />
      <p className="text-xs text-zinc-500">At least 10 characters.</p>
      {register.error ? (
        <p role="alert" className="text-sm text-red-600">
          {register.error instanceof ApiError ? register.error.message : "Could not create the account."}
        </p>
      ) : null}
      <button type="submit" disabled={register.isPending}
        className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
        {register.isPending ? "Creating…" : "Create account"}
      </button>
      <p className="text-sm">
        Already registered? <Link href="/login" className="underline">Sign in</Link>
      </p>
    </form>
  );
}
