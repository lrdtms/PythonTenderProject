# Slice 4 spike: PDF.js inside the Next 16 build

**Date:** 2026-10-16 · **Question:** does `pdfjs-dist` render a PDF page inside this Next.js 16.4.1 app with `cacheComponents` and `partialPrefetching` on, in `next dev` and in a production build, behind the single-origin `/api` proxy and the cookie session? (Slice 4 phase 2; the review screen in phase 4 depends on it.)

**Answer: yes.** Everything below was checked in a real browser (Chrome, driven by the browser tools) against a throwaway API and database (`inteltps_spike`, dropped afterwards), never the developer's dev database.

## Setup that worked first time

- `pdfjs-dist@6.4.299`, pinned exactly.
- Component `src/components/pdf/pdf-page.tsx`: `pdfjs-dist` is loaded with `await import("pdfjs-dist")` inside a `useEffect` (never on the server, only when a PDF is shown). The worker is configured with `GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString()`. No `next/dynamic`, no copy into `public/`, no `postinstall`: the fallbacks in the plan were not needed.
- `getDocument({ url, withCredentials: true })` against `/api/v1/document-versions/{id}/file` (authenticated, same origin; the file route sends `private, no-store` and `Content-Security-Policy: sandbox`, neither of which affects a `fetch`). `render({ canvas, viewport })` is the v6 signature.
- Build output: the worker ships as `.next/static/media/pdf.worker.min.*.mjs` (1,264,342 bytes, same size as the package file); the pdfjs chunk is about 455 KB and loads only when the viewer mounts; the spike route chunk itself is about 2 KB. Turbopack also compiles pdfjs into a ~433 KB server-side chunk that is never executed (it is reachable only from `useEffect`); `next/dynamic` with `ssr: false` would probably drop it. Not worth doing yet.

## Results (dev and production)

| Check | `next dev` | `next build` + `next start` |
|---|---|---|
| `?page=2` of a 3-page PDF | "Page 2 of 3", canvas shows the page text | same |
| `?page=99` (out of range) | clamps to "Page 3 of 3" | same |
| `?page=0` | clamps to "Page 1 of 3" | same |
| Unknown version id (a UUID that does not exist) | red alert "Could not display this document page…", canvas hidden, no blank canvas | not repeated (same code path) |
| Network | pdfjs chunk, worker and file all `200`; the file is served with the session cookie through the proxy | same |
| Console | no pdf.js errors or warnings | no errors |
| React Strict Mode (dev mounts the effect twice) | the first run is cancelled before it starts a task (log: `imported, cancelled=true`), the second renders; no leaked worker | n/a |

## Observations

- **Render latency in dev under browser automation was variable (about 2 to 8 seconds)** for a one-line page, while the document itself loads in under a second (`render start` to `render done` in temporary logs). `requestAnimationFrame` latency measured healthy (about 16 ms), and nothing hung: every render completed. Production completed within a few seconds every time. Not conclusive about the cause; re-measure with the real review screen in phase 4 (Performance panel) before optimising, and do not rely on fixed `wait()` calls in browser tests: poll for "Page N of M".
- **Two console messages are not ours:** a hydration mismatch on `<body data-demoway-document-id=…>` is injected by a browser extension on the author's machine; and Next's dev-only "instant navigation" diagnostic (fixed separately: the `(app)` segments opt out because the session guard is client-side by design).

## Decisions for phase 4

- Reuse `PdfPage`. It still lacks: separate document and page effects (today every page change re-downloads and re-parses the whole PDF), `devicePixelRatio` scaling (pages look soft on HiDPI screens), a text layer for highlighting the quote (the deterministic highlight is the stored `quote_start/quote_end` span shown in the extracted text beside the canvas), zoom and page controls, and UUID validation of the version id (the spike route does not validate it).
- Keep cancelling the render task and destroying the loading task on cleanup; reuse of one document across pages must keep `renderTask.cancel()` before starting the next render on the same canvas.
- Delete `src/app/(app)/dev/pdf-spike` when the review screen's viewer replaces it.
