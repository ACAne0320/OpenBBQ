import { clsx } from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ink" | "disabled";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  children: ReactNode;
};

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-accent text-paper shadow-control [@media(hover:hover)]:hover:bg-accent-hover",
  secondary: "bg-paper text-ink shadow-control [@media(hover:hover)]:hover:bg-paper-muted",
  ink: "bg-ink-brown text-paper shadow-control [@media(hover:hover)]:hover:bg-log-bg",
  disabled: "cursor-not-allowed bg-paper-side text-muted shadow-none"
};

export function Button({
  children,
  className,
  disabled = false,
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  const isDisabled = disabled || variant === "disabled";
  const effectiveVariant = isDisabled ? "disabled" : variant;

  return (
    <button
      type={type}
      className={clsx(
        "min-h-10 min-w-10 rounded-md px-3.5 text-sm font-medium transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:active:scale-100",
        variantClasses[effectiveVariant],
        className
      )}
      disabled={isDisabled}
      {...props}
    >
      {children}
    </button>
  );
}
