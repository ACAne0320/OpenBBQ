import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "oklch(95.6% 0.006 245)",
        paper: "oklch(99% 0.004 245)",
        "paper-muted": "oklch(96.8% 0.006 245)",
        "paper-side": "oklch(92.8% 0.008 245)",
        "paper-selected": "oklch(93.5% 0.026 248)",
        ink: "oklch(23% 0.014 245)",
        "ink-brown": "oklch(23% 0.014 245)",
        accent: "oklch(52% 0.112 248)",
        "accent-hover": "oklch(47% 0.118 248)",
        "accent-soft": "oklch(92% 0.046 248)",
        muted: "oklch(49% 0.017 245)",
        line: "oklch(88% 0.01 245)",
        ready: "oklch(48% 0.075 154)",
        "state-running": "oklch(91.8% 0.034 248)",
        "log-bg": "oklch(22% 0.018 245)",
        "log-panel": "oklch(27% 0.018 245)",
        "log-muted": "oklch(70% 0.018 245)",
        "log-text": "oklch(92% 0.009 245)",
        "log-warning": "oklch(78% 0.071 67)",
        "log-accent": "oklch(73% 0.082 248)",
        "log-error": "oklch(74% 0.086 38)"
      },
      borderRadius: {
        sm: "5px",
        md: "6px",
        lg: "7px",
        xl: "8px"
      },
      boxShadow: {
        panel: "0 10px 30px rgba(38,45,55,0.10), 0 1px 3px rgba(38,45,55,0.10)",
        control: "0 1px 3px rgba(38,45,55,0.12)",
        selected: "inset 0 0 0 1px rgba(55,102,190,0.24), 0 1px 3px rgba(38,45,55,0.10)",
        running: "inset 0 0 0 2px rgba(55,102,190,0.34)"
      }
    }
  },
  plugins: []
} satisfies Config;
