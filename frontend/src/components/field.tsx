import { useId, type InputHTMLAttributes } from "react";

type Props = { label: string } & InputHTMLAttributes<HTMLInputElement>;

export function Field({ label, ...input }: Props) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        {...input}
        className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700"
      />
    </div>
  );
}
