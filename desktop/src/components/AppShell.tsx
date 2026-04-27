import { clsx } from "clsx";
import type { ReactNode } from "react";

export type NavItem = "Home" | "New" | "Tasks" | "Results" | "Settings";

type AppShellProps = {
  active: NavItem;
  footerLabel: string;
  footerValue: string;
  children: ReactNode;
};

const navItems: NavItem[] = ["Home", "New", "Tasks", "Results", "Settings"];

export function AppShell({ active, footerLabel, footerValue, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-canvas p-[18px] text-ink">
      <div className="grid min-h-[calc(100vh-36px)] grid-cols-[104px_minmax(0,1fr)] gap-[18px]">
        <aside className="flex flex-col justify-between rounded-xl bg-paper-side px-3 py-3.5 shadow-control">
          <div>
            <div className="mb-7 font-serif text-xl leading-[0.94] text-ink-brown">
              Open
              <br />
              BBQ
            </div>
            <nav className="grid gap-2 text-xs" aria-label="Primary">
              {navItems.map((item) => (
                <a
                  key={item}
                  href={`#${item.toLowerCase()}`}
                  aria-current={active === item ? "page" : undefined}
                  className={clsx(
                    "min-h-10 rounded-sm px-2.5 py-2.5 transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    active === item
                      ? "bg-accent text-[#fff8ea] shadow-selected"
                      : "text-ink/75 [@media(hover:hover)]:hover:bg-paper-selected [@media(hover:hover)]:hover:text-ink"
                  )}
                >
                  {item}
                </a>
              ))}
            </nav>
          </div>
          <div className="text-[11px] leading-snug text-muted">
            {footerLabel}
            <br />
            <strong className="font-semibold text-ink">{footerValue}</strong>
          </div>
        </aside>
        {children}
      </div>
    </div>
  );
}
