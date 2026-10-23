# Hosted model, extraction operations and the remaining necessary changes

Written 23 Oct 2026 on `feat/slice-5b-estimate`, covering the commits after the Slice 5b docs: 2037117, 4759030, db8af7a, 5ff4ffd, dd2c6c7, 2e2c4aa and a55f9be. It records what was done, what was measured, how to run the system safely today, and what must change before real documents are processed. Known limitations are listed in [known-limitations.md](known-limitations.md#hosted-model-and-extraction-operations-22-23-oct-2026).

## Purpose

Extraction normally runs on a local Ollama model (`qwen3:4b`). A hosted OpenAI-compatible model can be used instead for speed. Until the POPIA assessment is done, a hosted model is for synthetic data only (see Operating rules). This document covers the hosted adapter, the job cancellation and progress features added to the Extraction panel, and what is still wrong.

## Configuring a hosted model

Settings live in `.env` (template: `.env.example`):

- `LLM_ALLOW_HOSTED=true` is required before any hosted provider is used.
- `LLM_PROVIDER=kimi` selects the hosted adapter (class `KimiLLM`). The name is historical: the adapter is any OpenAI-compatible chat API.
- `LLM_KIMI_BASE_URL`, `LLM_KIMI_MODEL` and `LLM_KIMI_API_KEY` set the endpoint, model and key. For Mammouth: `LLM_KIMI_BASE_URL=https://api.mammouth.ai/v1` and `LLM_KIMI_MODEL=claude-haiku-5-5`.
- `LLM_NUM_PREDICT` (default 2048) is the output-token cap. The hosted adapter sends it as `max_tokens` on every call, the same cap Ollama uses.

Two adapter details were added for reasons seen in practice:

- **User-Agent** (2037117): the adapter sends `User-Agent: IntelTPS/1.0`. Mammouth sits behind Cloudflare and answered HTTP 403 (error 1010) to urllib's default `Python-urllib` agent. Before the fix every hosted call failed and fell back to Ollama without an obvious error. A test pins the header.
- **Output cap** (4759030): some hosted models ignore `thinking: {type: disabled}` and spend the whole output budget on reasoning. The cap bounds that cost. It does not make the reply usable: a capped reply has no JSON.

Choosing a model: pick a model that answers without reasoning. Check one real-sized window before a long run (see the benchmark below).

Checking spend: the Mammouth key has a $2.00 / 30-day budget cap. `GET /key/info` shows usage (from the Mammouth docs). Keep the key out of the terminal output, for example:

```bash
KEY=$(grep '^LLM_KIMI_API_KEY=' .env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $KEY" https://api.mammouth.ai/key/info
```

UNVERIFIED: the host, path and auth header in that command were not checked against the Mammouth docs in this session; confirm them first. Do not paste the key into logs, chat or commits.

## Benchmark: one real-sized requirements window

Setup: one requirements window from synthetic pack02 (8 pages, 1 window, 10 ground-truth requirements), 2048-token output cap, same prompt and schema for every model, run 22 Oct 2026 through Mammouth.

| Model | Time | Reasoning tokens | Finish | Result | Approx. cost |
|---|---|---|---|---|---|
| claude-haiku-5-5 | 5.6 s | 0 | stop | Valid JSON, 10 of 10 requirements (rough word-overlap match; precision not scored) | about $0.0007 |
| qwen3.8-flash | 25.7 s | 2048 | length | Cut off, no JSON | about $0.001 |
| kimi-k2.6 | 23.8 s | 2048 | length | Cut off, no JSON | about $0.008 |

What it shows: the two non-Haiku models ignored the thinking switch, used the whole cap on reasoning and still billed for it. Haiku answered in one call with no reasoning tokens. The sample is one window on one synthetic pack, so it is not an accuracy study.

Earlier hosted attempts (before the fixes above) timed out at the 120 s client limit and fell back to Ollama window by window. The key-info endpoint showed about $0.28 of spend at one point.

Full-document run: a 265-page document (73 windows) on claude-haiku-5-5 ran all 73 windows at roughly 5 to 6 windows a minute with no hosted errors. But 22 of 73 windows ended `WINDOW_INVALID_OUTPUT`; the other windows gave 582 requirements, and 17 were `evidence_unverified`. The cause is UNVERIFIED. The most likely cause is the 2048-token cap truncating dense windows. The code retries a `length` result once with an `error=truncated` prompt, so a capped window costs two billed calls and still fails. Confirming this would mean resending that document's text to the hosted model, which was deliberately not done.

## Operating rules

- **Synthetic data only with any hosted model** until the POPIA assessment is done (project rule, README and PRD). The rule was not kept in every case: see item 11 in the necessary changes.
- **Check the adapter is really hosted.** A hosted failure falls back to Ollama. Look for `Kimi HTTP` warning lines in the api and worker logs (`docker compose logs worker`). A run that is much slower than expected is often a fallback.
- **Do not restart the worker during an extraction.** A restart kills the job; the lease expires and the job is retried from window 1, sending the text and billing again. Cancel the job first (below), wait for it to end, then restart.
- **Watch the spend** with `/key/info` before and after a long run.
- **Re-uploading a file starts a full billed extraction.** Do not upload the same file again to "refresh" it.

## Job cancellation

Endpoint: `POST /api/v1/jobs/{id}/cancel`. Permission: `review_data`. Responses:

- 403 for reviewer and project manager roles.
- 404 for a job in another organisation.
- 409 `tender_archived` on an archived tender.
- 409 `job_not_cancellable` for document-processing (`ingest_document`) jobs. Cancelling ingest would leave the document version stuck in pending or processing, so it is refused.
- Idempotent on finished jobs.

Behaviour:

- A queued job becomes `cancelled` at once.
- A running job is marked `cancelled`. The worker stops at its next `progress()` heartbeat by raising `JobCancelled` (`backend/app/kernel/errors.py`). No failure is recorded and nothing is retried. Results are written only in one transaction at the end of each handler, so a cancelled run stores nothing, and the runner checks again before committing.
- The unique active-job slot is freed, so extraction can be started again.
- An optional `on_cancel` hook on `JobHandler` closes the run in the worker after rollback. The API-side run close uses `skip_locked`, so it cannot wait on run rows.
- A cancelled job is never overwritten by a later failure: the requeue is guarded by `status='running'`, and `fail_run` never overwrites a cancelled run.
- Audit event `job_cancelled` records ids and enums only. The audit allow-list gained `job_type` and `subject_id`.

Deadlock found in review (fixed in dd2c6c7): the API held the job row while waiting for run-row locks the handler held; the handler's heartbeat, on a separate connection, then waited on the job row. Postgres could not detect it because the handler connection sat idle in a transaction. The regression test (cancel issued from inside `extract_boq`'s last progress call, from a second thread, 20 s join) now fails in about 25 s instead of hanging (2e2c4aa). The test was shown to fail when the bug was put back.

In the Extraction panel (a55f9be), "Cancel" appears on queued and running rows when the user has `review_data` and the tender is not archived, with an inline confirmation. Ingest jobs never appear in that panel, so Cancel is never offered for them.

Limits: see the known limitations section. In short, a cancel can land after the final check, one hosted call in flight still completes and bills, and a crash after cancel can leave a run `running`.

## Progress display

The Extraction panel shows a native progress bar and a plain-words line while a kind's job is queued or running (db8af7a). Helpers are `progressBounds`, `progressText` and `attemptText` in `frontend/src/lib/status-text.ts`.

- Requirements: "Reading section N of M".
- BoQ and quotation: "N of M steps".
- No usable count: "Working…".
- Queued: "Waiting in the queue…".
- A restarted run shows "Attempt N".

What the numbers mean: `progress_done` counts finished windows. "Section 44 of 73" means 44 windows are done. The count stays at the total during the post-window steps (merge, provenance, store), so the bar can read "73 of 73" for minutes before the run completes. One run showed 73 of 73 at about 14:27 UTC and completed at 14:30:41, about 3.5 minutes after the last window. Where the time goes inside a longer run is UNVERIFIED.

## Necessary changes

Ordered by priority. Size is a rough estimate, not measured.

1. **Investigate and fix the 22 invalid windows on large documents.** Why: on the 73-window run, 22 windows produced no requirements and the job still completed. Confirm the truncation cause on a synthetic dense pack (`pack09_xl`) first, then raise the hosted cap (for example to 4096) and/or reduce items per window. Size: medium.
2. **Stop wasting the retry on a capped reasoning reply.** Skip the `error=truncated` retry when the truncated reply is empty or does not start with `{` (reasoning used the whole budget). Add a per-job circuit breaker after two consecutive `length` results. Why: a capped window currently costs two billed calls. Size: small.
3. **Speed up provenance.** `attach_provenance` calls `locate()` once per requirement, and each call rebuilds the squashed text of all pages and, when there is no exact match, runs a fuzzy search page by page. Compute the squashed page text once per run, then re-measure the post-window time. Size: small to medium.
4. **Show the post-window phase in the progress display.** Add "Finding sources N of M" and make `progress_done` mean finished windows everywhere. Why: the bar sits at the total for minutes. Size: small.
5. **Reaper sweep for runs left `running` under a cancelled job** (for example after a crash after cancel). Size: medium.
6. **Restore a permission check in `cancel_runs_for_job`, or make it private.** Why: a permission check on that function was not confirmed when this document was written (UNVERIFIED against the current code). Size: small.
7. **Extraction panel polish:** cancel focus handling and clearing a failed-cancel message. Size: small.
8. **Rename the settings from `kimi` to a generic name** (`LLM_HOSTED_*`), with a migration note in `.env.example` and this document. Size: medium (settings, tests, docs).
9. **Guard against re-uploading the same file.** Check the document checksum within a tender, and warn across tenders, because each upload starts a full billed extraction. Size: small to medium.
10. **A data-handling gate.** When a hosted provider is configured and an uploaded document is not marked synthetic, refuse or warn, until the POPIA assessment is done. Size: medium.
11. **Privacy assessment item.** During this work a document that appears to be a real tender (not one of the synthetic packs) was processed with the hosted provider configured and uploaded several times. This was against the synthetic-only rule. Record it for the POPIA assessment; the file is not named here. Size: none (a decision and a record, not code). Items 10 and 11 should be settled together.
