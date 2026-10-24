# Slice 6b gate record (audit view, usage limits, operations)

**Date:** 2026-10-23 · **Branch:** `feat/slice-6b-operations` · **Spec:** `docs/superpowers/specs/2026-10-23-slice-6b-operations-design.md` · **Stack:** the real Docker Compose stack (db, api, worker, web, Caddy) rebuilt by `scripts/ops/start-demo.ps1`, driven through Caddy on `http://127.0.0.1:8080`; host Ollama running.

Each item is PASS, FAIL or NOT RUN. Nothing below is claimed that was not run.

## Exit-gate items

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Audit view | **PASS** (API; page by unit tests) | Scripted run against the live stack: admin and project manager get 200 with events; estimator and reviewer get 403; events carry the person's name; the action filter returns exactly the three `member_created` events; keyset paging returns disjoint pages; another organisation's events never appear. The page (filters, plain words, "Unknown user", metadata as text, Load more, 403 wording, nav link only for `view_audit`) is covered by Vitest. |
| 2 | Usage limits | **PASS** | Any member reads `GET /usage`; a non-admin gets 403 on the plan switch; the admin switches to `starter` (audited, metadata `demo` to `starter`); the 4th tender is refused with 403 `limit_exceeded` ("Active tenders limit reached on the Starter plan (3 of 3).") and nothing is created; the 4th member is refused; archiving a tender frees a slot. The refusal for uploads, storage, exports and the two-thread last-slot races (tenders, members) are in `tests/test_limits_enforcement.py` (14 tests). |
| 3 | Status | **PASS** | `GET /api/v1/health/status` with no login returned `{"api":"ok","database":"ok","model":"ok"}` (keys exactly api, database, model); `/status` was served without login. |
| 4 | One command | **PASS** | `start-demo.ps1` on the live stack: preflight, Docker check, model present and preloaded, `docker compose up -d --build`, health wait, summary and checklist printed. `start-demo.ps1 -Tunnel` with the development `.env` is refused with five named errors before Docker is touched (this run found a defect, see below). |
| 5 | Backup and restore | **PASS** | `backup.ps1` on the live stack: 23 tables and 78 files, manifest written. `restore.ps1 -Verify`: PASS (checksums, 23 tables, 78 files agree; scratch database dropped; live data untouched, 42 tenders before and after). A copy with one flipped byte in `db.dump`: FAIL naming `db_sha256 differs from the manifest`, before any restore work. `-Apply` without `-Project`, on the live project name, and with both switches: refused. `-Apply` into a second Compose project (`inteltps_gate`, Caddy on 8081): PASS; the restored stack reports 42 tenders (same as live), migration head advanced from 0007 to 0008, plans seeded, a stored PDF present in the restored files volume, `/api/v1/health/status` and `/status` answer on 8081. Gate project removed with `down -v`. |
| 6 | Tunnel | **NOT RUN** | `cloudflared` is not installed on the build machine. Checked instead: `tunnel.ps1` exits 2 with the install hint when `cloudflared` is absent; `tunnel.ps1 -Stop` is safe with no tunnel; the preflight rules that guard the tunnel are unit-tested and were exercised by `start-demo.ps1 -Tunnel`. The cloudflared start, URL capture and public health check have not been run. |
| 7 | Automated checks | **PASS** | See counts below. |

## Defect found by the gate and fixed

`start-demo.ps1 -Tunnel` with the unsafe development `.env` rebuilt and started the stack instead of refusing. Cause: `Invoke-Preflight` let the preflight tool's output into its return value, so the caller tested a non-empty array instead of a boolean. Fix with a test written first (`test_invoke_preflight_returns_a_plain_false_for_an_unsafe_tunnel_config`, RED then GREEN); the real-stack re-run now stops at "Fix the errors above". Note: the stack was rebuilt once by that faulty run; this only applied the 6b code and migration 0008 to the dev database, after a verified backup.

## Automated counts

Backend pytest 1201 passed (0 failed); frontend vitest 53 files, 631 tests passed; ruff check, ruff format check, lint-imports (6 contracts kept), pip-audit (runtime set, no known vulnerabilities), npm lint, typecheck and build clean. The final-review pass was a self-review by the implementer (no fresh reviewer was dispatched).

## Not covered

- The Cloudflare tunnel end to end (item 6).
- The new pages (`/audit`, `/settings/usage`, `/status`) were not opened in a browser by a person or by browser automation; they were served (HTTP 200), built, and covered by Vitest.
- `restore.ps1 -Apply` into the live project (`-IKnowThisReplacesLiveData`) was only checked to be refused without the flag.
- Backup while the stack is busy (`-Quiesce`) was not run; the backup was taken on an idle stack.
- The moment of a Windows restart, power loss or an Ollama crash during a demo.
