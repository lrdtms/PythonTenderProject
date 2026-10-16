"use client";

import { useEffect, useRef, useState } from "react";

import { clampPage } from "./clamp-page";

type State =
  | { status: "loading" }
  | { status: "ready"; numPages: number; shown: number }
  | { status: "error"; message: string };

/** A finished load, tagged with the request it answers. */
type Outcome = Exclude<State, { status: "loading" }> & { key: string };

type Props = { url: string; pageNumber: number; scale?: number };

/** Renders one page of a same-origin PDF to a canvas. pdfjs-dist is imported dynamically inside
 * the effect, so it never loads on the server and only loads when a PDF is shown. */
export function PdfPage({ url, pageNumber, scale = 1.25 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const key = `${url}\n${pageNumber}\n${scale}`;
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // "Loading" is derived: any outcome recorded for a different request is stale. This avoids a
  // synchronous setState at the top of the effect (react-hooks/set-state-in-effect).
  const state: State = outcome && outcome.key === key ? outcome : { status: "loading" };

  useEffect(() => {
    let cancelled = false;
    let loadingTask: { destroy: () => Promise<void> | void } | undefined;
    const setState = (next: Exclude<State, { status: "loading" }>) => setOutcome({ ...next, key });

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const task = pdfjs.getDocument({ url, withCredentials: true });
        loadingTask = task;
        const pdf = await task.promise;
        const shown = clampPage(pageNumber, pdf.numPages);
        const page = await pdf.getPage(shown);
        const canvas = canvasRef.current;
        if (cancelled || !canvas) return;
        const viewport = page.getViewport({ scale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvas, viewport }).promise;
        if (!cancelled) setState({ status: "ready", numPages: pdf.numPages, shown });
      } catch {
        if (!cancelled) {
          setState({
            status: "error",
            message: "Could not display this document page. Reload, or download the original file.",
          });
        }
      }
    })();

    return () => {
      cancelled = true;
      void loadingTask?.destroy();
    };
  }, [key, url, pageNumber, scale]);

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
      <canvas ref={canvasRef} className={state.status === "error" ? "hidden" : "max-w-full border"} />
    </div>
  );
}
