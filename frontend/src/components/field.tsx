import { useId, type InputHTMLAttributes } from "react";

type Props = { label: string } & InputHTMLAttributes<HTMLInputElement>;

export function Field({ label, ...input }: Props) {
  const id = useId();
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input id={id} {...input} className="input" />
    </div>
  );
}
