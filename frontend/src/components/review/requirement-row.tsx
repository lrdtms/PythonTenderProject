"use client";

import { useState } from "react";

import type { Requirement, RequirementPatch } from "@/api/types";
import { StatusBadge } from "@/components/status-badge";
import { MANDATORY_STATUSES, REQUIREMENT_TYPES, mandatoryLabel, requirementTypeLabel } from "@/lib/review-text";

import { type EditorApi, type ReplacedInfo, RowShell, type RowCommand } from "./row-shell";

type Props = {
  row: Requirement;
  versionId: string;
  selected: boolean;
  onSelect: () => void;
  archived?: boolean;
  command?: RowCommand;
  editing?: boolean;
  onEditingChange?: (open: boolean) => void;
  onReplaced?: (info: ReplacedInfo) => void;
};

function RequirementEditor({ row, save, cancel, saving, error }: { row: Requirement } & EditorApi) {
  const [description, setDescription] = useState(row.description);
  const [type, setType] = useState(row.requirement_type);
  const [mandatory, setMandatory] = useState(row.mandatory_status);
  const empty = description.trim() === "";
  const submit = () => {
    const patch: RequirementPatch = {};
    if (description.trim() !== row.description) patch.description = description.trim();
    if (type !== row.requirement_type) patch.requirement_type = type as RequirementPatch["requirement_type"];
    if (mandatory !== row.mandatory_status) patch.mandatory_status = mandatory as RequirementPatch["mandatory_status"];
    if (Object.keys(patch).length === 0) cancel();
    else save(patch);
  };
  return (
    <form
      className="space-y-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (!empty) submit();
      }}
    >
      <label className="block">
        <span className="font-medium">Requirement text</span>
        <textarea
          value={description}
          maxLength={2000}
          onChange={(e) => setDescription(e.target.value)}
          className="mt-1 w-full rounded border bg-transparent p-2"
          rows={3}
        />
      </label>
      <div className="flex flex-wrap gap-3">
        <label>
          <span className="mr-1 font-medium">Type</span>
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded border bg-transparent p-1">
            {REQUIREMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {requirementTypeLabel(t)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mr-1 font-medium">Status</span>
          <select value={mandatory} onChange={(e) => setMandatory(e.target.value)} className="rounded border bg-transparent p-1">
            {MANDATORY_STATUSES.map((m) => (
              <option key={m} value={m}>
                {mandatoryLabel(m)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {empty ? (
        <p role="alert" className="text-red-700 dark:text-red-300">
          The text cannot be empty.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-red-700 dark:text-red-300">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button type="submit" disabled={saving || empty} className="rounded border px-2 py-1 disabled:opacity-50">
          Save
        </button>
        <button type="button" disabled={saving} onClick={cancel} className="rounded border px-2 py-1 disabled:opacity-50">
          Cancel
        </button>
      </div>
    </form>
  );
}

export function RequirementRow({ row, versionId, selected, onSelect, archived = false, command, editing, onEditingChange, onReplaced }: Props) {
  const original = row.review_status === "corrected" ? (row.original_value as { description?: string }) : null;
  return (
    <RowShell
      kind="requirement"
      versionId={versionId}
      row={row}
      selected={selected}
      onSelect={onSelect}
      archived={archived}
      command={command}
      editing={editing}
      onEditingChange={onEditingChange}
      onReplaced={onReplaced}
      chips={
        <>
          <StatusBadge tone="neutral" label={requirementTypeLabel(row.requirement_type)} />
          <StatusBadge tone="neutral" label={mandatoryLabel(row.mandatory_status)} />
          {row.evidence_status === "evidence_unverified" ? <StatusBadge tone="warning" label="Evidence unverified" /> : null}
          {row.needs_review ? <StatusBadge tone="warning" label="Needs review" /> : null}
        </>
      }
      summary={
        <>
          <p className="text-sm">{row.description}</p>
          {original?.description && original.description !== row.description ? (
            <p className="mt-1 text-xs text-zinc-500">Originally: {original.description}</p>
          ) : null}
          {row.page_number ? <p className="mt-1 text-xs text-zinc-500">Page {row.page_number}</p> : null}
        </>
      }
      editor={(api) => <RequirementEditor row={row} {...api} />}
    />
  );
}
