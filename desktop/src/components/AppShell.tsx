import { clsx } from "clsx";
import { FilePlus2, ListChecks, Settings } from "lucide-react";
import type { ReactNode } from "react";

import openbbqIconColor from "../assets/openbbq-icon-color.png";

export type NavItem = "New" | "Tasks" | "Settings";

type AppShellProps = {
  active?: NavItem;
  footerLabel: string;
  footerValue: string;
  onNavigate?: (item: NavItem) => void;
  children: ReactNode;
};

const navItems: NavItem[] = ["New", "Tasks", "Settings"];
const navIcons = {
  New: FilePlus2,
  Tasks: ListChecks,
  Settings
} satisfies Record<NavItem, typeof FilePlus2>;

export function AppShell({ active, footerLabel, footerValue, onNavigate, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-canvas p-3 text-ink sm:p-4">
      <div className="grid min-h-[calc(100vh-24px)] grid-cols-1 gap-3 sm:min-h-[calc(100vh-32px)] xl:grid-cols-[212px_minmax(0,1fr)] xl:gap-4">
        <aside className="flex flex-col justify-between rounded-xl bg-paper-side px-3 py-3 shadow-control">
          <div>
            <div className="mb-4 flex items-center gap-2 px-1.5 text-[15px] font-semibold tracking-[-0.012em] text-ink-brown">
              <img className="h-7 w-7 shrink-0" src={openbbqIconColor} alt="OpenBBQ" />
              <span className="min-w-0 truncate">OpenBBQ</span>
            </div>
            <nav className="grid grid-cols-3 gap-1 text-xs xl:grid-cols-1 xl:gap-1" aria-label="Primary">
              {navItems.map((item) => {
                const Icon = navIcons[item];
                return (
                  <button
                    key={item}
                    type="button"
                    aria-label={item}
                    aria-current={active === item ? "page" : undefined}
                    onClick={() => onNavigate?.(item)}
                    className={clsx(
                      "flex min-h-10 items-center justify-center gap-2 rounded-md px-2.5 py-2.5 text-center transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent xl:justify-start xl:text-left",
                      active === item
                        ? "bg-paper text-ink shadow-selected"
                        : "text-muted [@media(hover:hover)]:hover:bg-paper [@media(hover:hover)]:hover:text-ink"
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span className="hidden xl:inline">{item}</span>
                  </button>
                );
              })}
            </nav>
          </div>
          <div className="mt-4 hidden rounded-lg bg-paper/75 px-3 py-2.5 text-[11px] leading-snug text-muted shadow-control xl:block">
            <span className="block uppercase">{footerLabel}</span>
            <strong className="mt-1 block truncate font-semibold text-ink">{footerValue}</strong>
          </div>
        </aside>
        <main className="min-w-0 overflow-hidden rounded-xl bg-paper shadow-panel">
          <div className="min-h-full p-4 sm:p-5 xl:p-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
