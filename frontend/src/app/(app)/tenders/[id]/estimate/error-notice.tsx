import { ApiError } from "@/api/errors";
import { notReadyBlockers } from "@/api/estimates";
import { blockerReasonText, errorText } from "@/lib/estimate-words";

const MAX_SHOWN = 10;

/** A failed estimate action in plain words, with the blockers of an `estimate_not_ready` refusal listed. */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const text = error instanceof ApiError ? errorText(error.code, error.message) : "Something went wrong. Try again.";
  const blockers = notReadyBlockers(error);
  const shown = blockers.slice(0, MAX_SHOWN);
  const hidden = blockers.length - shown.length;
  return (
    <div role="alert" className="mb-3 text-sm text-red-700 dark:text-red-300">
      <p>{text}</p>
      {blockers.length > 1 ? <p className="mt-1">{blockers.length} lines need attention.</p> : null}
      {shown.length > 0 ? (
        <ul className="mt-1 list-disc pl-5">
          {shown.map((b, i) => {
            const name = [b.item_no, b.description].filter(Boolean).join(" ");
            return (
              <li key={`${b.code}-${b.line_id ?? "none"}-${i}`}>
                {name ? `${name}: ` : ""}
                {blockerReasonText(b.code, b.reasons)}
                {b.line_id ? (
                  <>
                    {" "}
                    <a href={`#line-${b.line_id}`} className="underline">
                      Go to the line
                    </a>
                  </>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {hidden > 0 ? <p className="mt-1">{`and ${hidden} more`}</p> : null}
    </div>
  );
}
