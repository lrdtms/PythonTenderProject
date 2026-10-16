"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { meQueryOptions, useLogin } from "@/api/session";
import { Field } from "@/components/field";

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();
  const { data: me, isPending } = useQuery(meQueryOptions);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (me) router.replace("/tenders");
  }, [me, router]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (login.isPending) return;
    login.mutate({ email, password });
  }

  if (isPending || me) {
    return <p role="status" className="text-sm text-zinc-500">Loading…</p>;
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <h2 className="text-xl font-medium">Sign in</h2>
      <Field label="Email" type="email" autoComplete="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="current-password" required
        value={password} onChange={(e) => setPassword(e.target.value)} />
      {login.error ? (
        <p role="alert" className="text-sm text-red-600">
          {login.error instanceof ApiError ? login.error.message : "Could not sign in."}
        </p>
      ) : null}
      <button type="submit" disabled={login.isPending}
        className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
        {login.isPending ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-sm">
        New here? <Link href="/register" className="underline">Create an account</Link>
      </p>
    </form>
  );
}
