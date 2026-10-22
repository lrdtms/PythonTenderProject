import { ApiError } from "@/api/errors";
import { notReadyBlockers } from "@/api/estimates";
import { blockerText, errorText } from "@/lib/estimate-words";

/** A failed estimate action in plain words, with the blockers of an `estimate_not_ready` refusal listed. */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const text = error instanceof ApiError ? errorText(error.code, error.message) : "Something went wrong. Try again.";
  const blockers = notReadyBlockers(error);
  return (
    <div role="alert" className="mb-3 text-sm text-red-700 dark:text-red-300">
      <p>{text}</p>
      {blockers.length > 0 ? (
        <ul className="mt-1 list-disc pl-5">
          {blockers.map((b, i) => (
            <li key={`${b.code}-${b.line_id ?? "none"}-${i}`}>
              {blockerText(b.code)}
              {b.line_id ? (
                <>
                  {" "}
                  <a href={`#line-${b.line_id}`} className="underline">
                    Go to the line
                  </a>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
