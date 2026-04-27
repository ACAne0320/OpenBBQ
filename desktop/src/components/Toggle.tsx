import { clsx } from "clsx";

type ToggleProps = {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange?: (checked: boolean) => void;
};

export function Toggle({ checked, disabled = false, label, onChange }: ToggleProps) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={checked}
      disabled={disabled}
      onClick={() => {
        if (!disabled) {
          onChange?.(!checked);
        }
      }}
      className={clsx(
        "relative inline-flex h-10 w-14 items-center rounded-full transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:active:scale-100",
        disabled
          ? "bg-[#c9b79c] shadow-none"
          : checked
            ? "bg-accent shadow-selected"
            : "bg-[#d8c8b1] shadow-control [@media(hover:hover)]:hover:bg-[#d0bfa6]"
      )}
    >
      <span
        className={clsx(
          "absolute left-1.5 h-7 w-7 rounded-full bg-[#fff8ea] shadow-control transition-transform duration-150",
          checked ? "translate-x-5" : "translate-x-0"
        )}
      />
    </button>
  );
}
