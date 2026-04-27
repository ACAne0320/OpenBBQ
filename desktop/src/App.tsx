import { AppShell } from "./components/AppShell";

export function App() {
  return (
    <AppShell active="New" footerLabel="Workspace" footerValue="creator-videos">
      <main className="rounded-xl bg-paper p-6 shadow-panel">
        <p className="text-xs uppercase text-muted">OpenBBQ Desktop</p>
        <h1 className="mt-2 font-serif text-[40px] leading-none text-ink-brown">New subtitle task</h1>
        <p className="mt-4 max-w-xl text-sm leading-6 text-muted">
          Source import and workflow setup will replace this work surface in the next renderer task.
        </p>
      </main>
    </AppShell>
  );
}
