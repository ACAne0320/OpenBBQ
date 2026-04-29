import { clsx } from "clsx";
import type { ButtonHTMLAttributes } from "react";

type ToggleButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "aria-checked" | "aria-label" | "aria-pressed" | "disabled" | "onChange" | "onClick" | "role" | "type"
>;

type ToggleProps = ToggleButtonProps & {
  checked: boolean;
  disabled?: boolean;
  onChange?: (checked: boolean) => void;
} & ({ label: string; "aria-label"?: string } | { label?: string; "aria-label": string });

export function Toggle({
  checked,
  className,
  disabled = false,
  label,
  onChange,
  "aria-label": ariaLabel,
  ...props
}: ToggleProps) {
  return (
    <button
      {...props}
      type="button"
      role="switch"
      aria-label={ariaLabel ?? label}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => {
        if (!disabled) {
          onChange?.(!checked);
        }
      }}
      className={clsx(
        "relative inline-flex h-10 w-14 items-center rounded-full transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:active:scale-100",
        disabled
          ? "bg-paper-side shadow-none"
          : checked
            ? "bg-accent shadow-selected"
            : "bg-paper-side shadow-control [@media(hover:hover)]:hover:bg-state-running",
        className
      )}
    >
      <span
        className={clsx(
          "absolute left-1.5 h-7 w-7 rounded-full bg-paper shadow-control transition-transform duration-150",
          checked ? "translate-x-5" : "translate-x-0"
        )}
      />
    </button>
  );
}
