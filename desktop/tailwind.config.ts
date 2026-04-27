import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "oklch(94% 0.025 82)",
        paper: "#fffaf0",
        "paper-muted": "#f8f1e5",
        "paper-side": "#eee1cc",
        "paper-selected": "#efe0c9",
        ink: "#20251f",
        "ink-brown": "#3b2a1f",
        accent: "#b6632f",
        "accent-soft": "#ead3c1",
        muted: "#6d6251",
        line: "#dfd0ba",
        ready: "#6f7c46",
        "log-bg": "#2d241d"
      },
      borderRadius: {
        sm: "5px",
        md: "6px",
        lg: "7px",
        xl: "8px"
      },
      boxShadow: {
        panel: "0 2px 10px rgba(38,33,22,0.14)",
        control: "0 1px 4px rgba(38,33,22,0.12)",
        selected: "inset 0 0 0 1px rgba(182,99,47,0.2), 0 1px 3px rgba(93,55,28,0.1)"
      }
    }
  },
  plugins: []
} satisfies Config;
