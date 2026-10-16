"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { type ReviewKind, type ReviewVars, useReviewMutation } from "@/api/review";
import type { BoqPatch, RequirementPatch } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { reviewStatusLabel, reviewTone, writeErrorText } from "@/lib/review-text";

/** A keyboard command addressed to one row. `nonce` makes repeating the same action fire again. */
export type RowCommand = { action: "confirm" | "reject"; id: string; nonce: number };

export type RowMeta = {
  id: string;
  review_status: string;
  reviewed_by_name?: string | null;
  reviewed_at?: string | null;
};

export type EditorApi = {
  save: (patch: BoqPatch | RequirementPatch) => void;
  cancel: () => void;
  saving: boolean;
  error: string | null;
};

/** What the screen is told when a write found its row gone. */
export type ReplacedInfo = { patch?: BoqPatch | RequirementPatch };

type Props = {
  kind: ReviewKind;
  versionId: string;
  row: RowMeta;
  selected: boolean;
  onSelect: () => void;
  archived: boolean;
  /** Keyboard confirm/reject; acted on only when `command.id` is this row. */
  command?: RowCommand;
  /** Controlled editor state (the screen owns it so the `e` key can open it). */
  editing?: boolean;
  onEditingChange?: (open: boolean) => void;
  onReplaced?: (info: ReplacedInfo) => void;
  summary: ReactNode;
  chips?: ReactNode;
  editor: (api: EditorApi) => ReactNode;
};

const BUTTON = "rounded border px-2 py-1 text-sm disabled:opacity-50";

export function RowShell({
  kind, versionId, row, selected, onSelect, archived, command, editing: editingProp, onEditingChange, onReplaced, summary, chips, editor,
}: Props) {
  const canReview = useCan("review_data") && !archived;
  const { mutate, isPending } = useReviewMutation(kind, versionId);
  const [localEditing, setLocalEditing] = useState(false);
  const [note, setNote] = useState<{ text: string; replaced: boolean } | null>(null);
  const handled = useRef(command?.nonce ?? 0);
  const editing = editingProp ?? localEditing;
  const setEditing = onEditingChange ?? setLocalEditing;

  // No synchronous setState here: the keyboard path calls this from an effect.
  const run = (vars: ReviewVars, after?: () => void) => {
    mutate(vars, {
      onSuccess: () => {
        setNote(null);
        after?.();
      },
      onError: (error) => {
        const described = writeErrorText(error);
        setNote(described);
        if (described.replaced) onReplaced?.({ patch: vars.action === "correct" ? vars.patch : undefined });
      },
    });
  };

  useEffect(() => {
    if (!command || command.nonce === handled.current) return;
    handled.current = command.nonce;
    if (command.id !== row.id || !canReview || isPending) return;
    run({ action: command.action, id: row.id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [command]);

  const reviewer =
    row.reviewed_by_name && row.reviewed_at
      ? `Reviewed by ${row.reviewed_by_name} on ${formatDateTime(row.reviewed_at)}`
      : null;

  return (
    <li
      aria-current={selected ? "true" : undefined}
      className={`rounded border p-3 ${selected ? "border-blue-600 ring-1 ring-blue-600" : "border-zinc-300 dark:border-zinc-700"}`}
    >
      <button
        type="button"
        onClick={onSelect}
        className="block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600"
      >
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <StatusBadge tone={reviewTone(row.review_status)} label={reviewStatusLabel(row.review_status)} />
          {chips}
        </div>
        {summary}
      </button>
      {reviewer ? <p className="mt-1 text-xs text-zinc-500">{reviewer}</p> : null}
      {note && !editing ? (
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
          {note.text}
        </p>
      ) : null}
      {editing ? (
        <div className="mt-2">
          {editor({
            saving: isPending,
            error: note && !note.replaced ? note.text : null,
            cancel: () => setEditing(false),
            save: (patch) => run({ action: "correct", id: row.id, patch }, () => setEditing(false)),
          })}
        </div>
      ) : canReview && !note?.replaced ? (
        <div className="mt-2 flex gap-2">
          <button type="button" disabled={isPending} onClick={() => run({ action: "confirm", id: row.id })} className={BUTTON}>
            Confirm
          </button>
          <button type="button" disabled={isPending} onClick={() => setEditing(true)} className={BUTTON}>
            Edit
          </button>
          <button type="button" disabled={isPending} onClick={() => run({ action: "reject", id: row.id })} className={BUTTON}>
            Reject
          </button>
        </div>
      ) : null}
    </li>
  );
}
