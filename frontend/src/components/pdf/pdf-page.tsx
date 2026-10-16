"use client";

import { useEffect, useRef, useState } from "react";

import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";

import { clampPage } from "./clamp-page";

/** Destroying a loading task can reject (e.g. worker already gone); that must not surface as an
 * unhandled rejection. */
function destroyQuietly(task: { destroy: () => Promise<void> | void }): void {
  Promise.resolve(task.destroy()).catch(() => {});
}

type Failure = { url: string; message: string };
type Loaded = { url: string; pdf: PDFDocumentProxy };
/** A finished render, tagged with the request it answers. */
type Shown = { key: string; shown: number } | { key: string; error: string };

type Props = { url: string; pageNumber: number; scale?: number; onDocument?: (numPages: number) => void };

const FAILURE = "Could not display this document page. Reload, or download the original file.";

/** Renders one page of a same-origin PDF to a canvas. pdfjs-dist is imported dynamically inside
 * the effect, so it never loads on the server and only loads when a PDF is shown. The document is
 * loaded once per URL; changing the page only renders again. */
export function PdfPage({ url, pageNumber, scale = 1.25, onDocument }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const onDocumentRef = useRef(onDocument);
  useEffect(() => {
    onDocumentRef.current = onDocument;
  });

  // Effect 1: the document, keyed on the URL only.
  useEffect(() => {
    let cancelled = false;
    let loadingTask: PDFDocumentLoadingTask | undefined;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        // Cleanup may already have run (Strict Mode remount, navigation during the chunk load):
        // never start a fetch and a worker that nothing will destroy.
        if (cancelled) return;
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const task = pdfjs.getDocument({ url });
        loadingTask = task;
        const pdf = await task.promise;
        if (cancelled) return;
        setLoaded({ url, pdf });
        onDocumentRef.current?.(pdf.numPages);
      } catch {
        if (!cancelled) setFailure({ url, message: FAILURE });
      }
    })();
    return () => {
      cancelled = true;
      if (loadingTask) destroyQuietly(loadingTask);
    };
  }, [url]);

  // Effect 2: the page, keyed on the loaded document, page and scale.
  const pdf = loaded && loaded.url === url ? loaded.pdf : null;
  const key = `${url}
${pageNumber}
${scale}`;
  // A page past the end is not drawn as the last page: the row cites a page this file lacks.
  const beyondEnd = !!pdf && pageNumber > pdf.numPages;
  useEffect(() => {
    if (!pdf || beyondEnd) return;
    let cancelled = false;
    let renderTask: RenderTask | undefined;
    (async () => {
      try {
        const wanted = clampPage(pageNumber, pdf.numPages);
        const page = await pdf.getPage(wanted);
        const canvas = canvasRef.current;
        if (cancelled || !canvas) return;
        const dpr = typeof window === "undefined" ? 1 : Math.max(1, window.devicePixelRatio || 1);
        const viewport = page.getViewport({ scale: scale * dpr });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        // CSS size stays in layout pixels; the extra canvas pixels keep HiDPI screens sharp.
        canvas.style.width = `${viewport.width / dpr}px`;
        renderTask = page.render({ canvas, viewport });
        await renderTask.promise;
        if (!cancelled) setShown({ key, shown: wanted });
      } catch {
        // After cleanup, rejections (RenderingCancelledException) are expected.
        if (!cancelled) setShown({ key, error: FAILURE });
      }
    })();
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [pdf, pageNumber, scale, key, beyondEnd]);

  const documentFailed = failure && failure.url === url ? failure.message : null;
  const outcome = shown && shown.key === key ? shown : null;
  const error = documentFailed ?? (beyondEnd ? `This document has no page ${pageNumber}.` : null) ?? (outcome && "error" in outcome ? outcome.error : null);
  const ready = outcome && "shown" in outcome && pdf ? { shown: outcome.shown, numPages: pdf.numPages } : null;
  const state = error ? ({ status: "error", message: error } as const) : ready ? ({ status: "ready", ...ready } as const) : ({ status: "loading" } as const);

  return (
    <div>
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-zinc-500">Loading page…</p>
      ) : null}
      {state.status === "error" ? (
        <p role="alert" className="text-sm text-red-600">{state.message}</p>
      ) : null}
      {state.status === "ready" ? (
        <p className="mb-1 text-xs text-zinc-500">
          Page {state.shown} of {state.numPages}
        </p>
      ) : null}
      {/* Hidden on error (never a blank canvas); invisible while loading so the previous page's
          pixels do not show under "Loading page…". */}
      <canvas
        ref={canvasRef}
        data-testid="pdf-canvas"
        className={
          state.status === "error"
            ? "hidden"
            : state.status === "loading"
              ? "invisible max-w-full border"
              : "max-w-full border"
        }
      />

    </div>
  );
}
