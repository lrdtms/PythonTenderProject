# ADR-0010: Solo build: reduced scope and server-side sessions

- **Status:** Accepted (amends ADR-0008 and the team split in architecture.md section 7)
- **Date:** 2026-10-15
- **Deciders:** project owner

## Context and Problem Statement
The architecture and plan assumed four people. The project is now built by one person (with AI assistance) in the same 32 days. Which scope and which auth design still fit?

## Decision Drivers
- A working end-to-end system by the deadline beats a wide, unfinished one
- Security marks (10) and tenant isolation remain non-negotiable
- Less custom security-critical code is better when no one else reviews it

## Considered Options
1. Keep the full team scope and ADR-0008 as written
2. **Cut scope up front (see below) and use server-side sessions**
3. Cut scope and adopt a hosted identity provider

## Decision Outcome
Chosen option: **Option 2.**
- **Auth:** server-side sessions. The login creates a random 256-bit token, stored hashed (SHA-256) in `sessions` with user, active organisation, expiry and revocation; sent as an `HttpOnly; SameSite=Lax; Secure` cookie. The role is read from the database on every request (unchanged from ADR-0008), so deactivation and role changes apply immediately. No JWT and no refresh rotation: logout and deactivation simply revoke rows. CSRF protection is unchanged: a required custom header on state-changing requests plus SameSite.
- **Passwords:** Argon2id (unchanged).
- **One user, one organisation:** one user belongs to one organisation; `create_member` rejects emails that already exist (409), and registration does the same. The password hash lives on the global `users` row, so an admin password reset changes it for that one account and revokes ALL of the user's sessions, not only those for the admin's organisation. Multi-organisation membership and switching organisation (ADR-0008) are out of scope; adding them requires revisiting admin password reset first, because an admin of one organisation must never be able to set the password of a user who also belongs to another.
- **Scope cuts:** Q&A (US-06), email notifications and invites, a separate Platform Admin role, and a staging environment are out. Admins create member accounts directly. Roles: admin, estimator, project manager, reviewer. Billing stays a plan table with enforced limits and no payment gateway.
- **Unchanged:** modular monolith, tenant isolation (ADR-0005), Postgres queue (ADR-0006), storage port (ADR-0007), pre-filter extraction (ADR-0004 as updated), single origin (ADR-0009, minus Q&A streaming).

### Consequences
- Positive: less security-critical code to own and test; faster to build; revocation is trivial.
- Negative / Tradeoff: one session lookup per request (negligible here); no password reset by email (admin reset instead); fewer features to demonstrate.
- Follow-ups: Q&A can return as a stretch if every slice is finished early.

## Links / References
- ADR-0005, ADR-0008, docs/plan.md (solo plan), OWASP Session Management cheat sheet
