"use client";

import { useEffect, useRef } from "react";

import { splitQuoteSpan } from "@/lib/source-span";

type Props = { text: string; start: number | null; end: number | null; quote?: string | null };

/** The page's extracted text with the stored quote span marked (offsets are into the squashed text, see splitQuoteSpan). Everything is a text node, so
 * document content can never become markup. Bad offsets show the text unmarked. */
export function PageText({ text, start, end, quote }: Props) {
  const markRef = useRef<HTMLElement>(null);
  const span = splitQuoteSpan(text, start, end);
  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [span?.mark, start, end]);

  return (
    <div>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap panel p-3 text-sm">
        {span ? (
          <>
            {span.before}
            <mark ref={markRef} className="bg-yellow-200 text-black underline decoration-2">
              {span.mark}
            </mark>
            {span.after}
          </>
        ) : (
          text
        )}
      </pre>
      {!span && quote ? (
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Quote (not located on the page): <q>{quote}</q>
        </p>
      ) : null}
    </div>
  );
}
