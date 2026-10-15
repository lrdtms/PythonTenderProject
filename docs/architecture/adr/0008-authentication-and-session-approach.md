# ADR-0008: Self-managed authentication with short JWT cookie, rotating refresh token, roles from DB

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
The PRD picks email/password with Argon2/bcrypt and JWT in httpOnly cookies with role claims. Roles can change (FR-04 deactivate/role change) and users can belong to several organisations. The link is public via a tunnel. How do we authenticate and authorise without stale permissions or CSRF exposure?

## Decision Drivers
- Base spec §4.3: secure password handling, backend authorisation, rate limiting
- Immediate effect of deactivation/role change
- No external auth provider cost or dependency (Auth0/Clerk would also send user data abroad)
- Single origin (ADR-0009)

## Considered Options
1. **Self-managed: Argon2id; access JWT (15 min) + opaque rotating refresh token (hashed in DB), both httpOnly cookies; role resolved from DB per request**
2. Same, but trust role claims inside the JWT
3. Hosted identity provider (Auth0, Clerk, Supabase Auth)
4. Server-side sessions only (session table, no JWT)

## Decision Outcome
Chosen option: **Option 1**.
- Passwords: Argon2id (`argon2-cffi`), minimum length 10, breached-password check optional.
- Cookies: `access_token` (JWT: `sub`, `org` = active organisation, `exp` 15 min) and `refresh_token` (random 256-bit, stored as SHA-256 in `refresh_tokens` with `family_id`, rotated on every use; reuse of a rotated token revokes the family). `HttpOnly; Secure; SameSite=Lax; Path=/api` (refresh: `Path=/api/auth/refresh`).
- Authorisation: every request loads the membership `(user, org)` and its role from the DB (one indexed query, cheap at our scale). The JWT carries **no role**. Deactivation takes effect on the next request. Switching organisation = `POST /auth/switch-org`, which re-issues the access token after a membership check.
- CSRF: same-origin + `SameSite=Lax`, plus a required custom header (`X-Requested-With`) on state-changing requests, which cross-site forms cannot send.
- Rate limits (slowapi): login, register, refresh, invites, upload, ask.
- Audit: login success/failure, role change, invite, deactivation.

### Consequences
- Positive: no stale roles, revocable sessions (logout deletes the refresh family), no third party.
- Negative / Tradeoff: we own security-critical code (hashing parameters, token rotation, reset flow). Password reset by email is a stretch; MVP uses admin-issued invites/resets. One DB read per request for the membership (negligible here, would need caching at scale).
- Follow-ups: security tests for privilege escalation, expired/reused refresh, deactivated user.

## Pros and Cons of the Options

### Option 1
- Good: correct revocation semantics, simple mental model.
- Bad: more code than a provider.

### Option 2
- Good: no per-request DB read.
- Bad: role changes and deactivation lag up to token lifetime; multi-org claims get complex.

### Option 3
- Good: MFA, resets, hardened flows for free.
- Bad: cross-border transfer of personal information (POPIA), vendor setup time, tunnel URL changes break callback URLs.

### Option 4
- Good: simplest revocation.
- Bad: equally valid; rejected only because the PRD and team already chose JWT. Option 1 is close to this in practice.

## Links / References
- Base spec §4.3, FR-01..FR-04; PRD §7 stack; OWASP Password Storage and Session Management cheat sheets
