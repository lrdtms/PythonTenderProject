"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useLogout } from "@/api/session";
import type { Role } from "@/api/types";

import { useSession } from "./auth-gate";

const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  estimator: "Estimator",
  project_manager: "Project manager",
  reviewer: "Reviewer",
};

function NavLink({ href, pathname, onNavigate, children }: { href: string; pathname: string; onNavigate: () => void; children: ReactNode }) {
  const current = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link href={href} className="nav-item" aria-current={current ? "page" : undefined} onClick={onNavigate}>
      {children}
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const me = useSession();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const logout = useLogout();
  // On a phone the sidebar is a full-screen menu; on a desktop it is always shown (see globals.css).
  const [menuOpen, setMenuOpen] = useState(false);
  const close = () => setMenuOpen(false);
  const can = (permission: string) => me.permissions.includes(permission);
  const admin = can("manage_members") || can("view_audit") || can("manage_pricing");

  return (
    <div className="shell">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded focus:bg-white focus:p-2 focus:text-black"
      >
        Skip to content
      </a>
      <header className="shell-head">
        <Link href="/tenders" className="shell-brand" onClick={close}>
          <span className="shell-mark" aria-hidden="true">I</span>
          IntelTPS
        </Link>
        <div className="flex min-w-0 items-center gap-3 text-sm">
          <span className="hidden min-w-0 truncate text-zinc-500 sm:inline">
            {me.organisation_name} · {me.name}, {ROLE_LABELS[me.role]}
          </span>
          <button
            type="button"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSuccess: () => router.replace("/login") })}
            className="btn"
          >
            Sign out
          </button>
          <button
            type="button"
            className="btn menu-button"
            aria-expanded={menuOpen}
            aria-controls="main-nav"
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
      </header>
      <nav id="main-nav" aria-label="Main" className="shell-side" data-open={menuOpen}>
        <NavLink href="/tenders" pathname={pathname} onNavigate={close}>Tenders</NavLink>
        <NavLink href="/suppliers" pathname={pathname} onNavigate={close}>Suppliers</NavLink>
        <NavLink href="/settings/usage" pathname={pathname} onNavigate={close}>Usage</NavLink>
        {admin ? <p className="nav-group">Organisation</p> : null}
        {can("manage_members") ? <NavLink href="/members" pathname={pathname} onNavigate={close}>Members</NavLink> : null}
        {can("manage_pricing") ? <NavLink href="/settings/pricing" pathname={pathname} onNavigate={close}>Pricing</NavLink> : null}
        {can("view_audit") ? <NavLink href="/audit" pathname={pathname} onNavigate={close}>Audit</NavLink> : null}
      </nav>
      <div className="shell-sheet">
        {logout.isError ? (
          <p role="alert" className="notice m-4">
            Could not sign out. Try again.
          </p>
        ) : null}
        <main id="main" className="w-full max-w-[1440px] p-4 sm:p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
