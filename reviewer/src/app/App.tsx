import { useEffect, useState } from "react";
import { LoaderCircle, RotateCcw } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { CueListPanel } from "../cues/CueListPanel";
import { CueEditor } from "../editor/CueEditor";
import { AddTermDialog } from "../glossary/AddTermDialog";
import { PlayerPanel } from "../player/PlayerPanel";
import { TimelineDock } from "../timeline/TimelineDock";
import { CompletionBanner } from "./CompletionBanner";
import { useI18n } from "./i18n";
import { Resizer } from "./Resizer";
import {
  createAppServices,
  ServicesProvider,
  useAppSelector,
  useServices,
  type AppServices,
} from "./services";
import { ShortcutHelp } from "./ShortcutHelp";
import { useGlobalShortcuts } from "./shortcuts";
import { TopBar } from "./TopBar";

export function App() {
  const [services] = useState(() => createAppServices());
  return (
    <ServicesProvider services={services}>
      <AppShell services={services} />
    </ServicesProvider>
  );
}

function AppShell({ services }: { services: AppServices }) {
  const { t } = useI18n();
  const { store, commands, api } = services;
  useGlobalShortcuts(services);

  useEffect(() => {
    commands.setLocalizer(t);
  }, [commands, t]);

  useEffect(() => {
    void commands.load();
  }, [commands]);

  // Preview polling: kick off transcode when needed, refresh until ready.
  const mediaPlayable = useAppSelector((state) => state.session?.media.playable ?? null);
  const previewStatus = useAppSelector(
    (state) => state.session?.media.preview_status ?? null,
  );
  useEffect(() => {
    if (mediaPlayable == null || mediaPlayable || previewStatus === "failed") return;
    let cancelled = false;
    if (previewStatus === "needed") {
      void api.startPreview().catch(commands.handleError.bind(commands));
    }
    const timer = window.setInterval(async () => {
      try {
        const state = await api.previewStatus();
        if (cancelled) return;
        if (state.status === "ready") {
          window.clearInterval(timer);
          store.setState({ session: await api.session() });
        } else {
          store.setState((current) =>
            current.session
              ? {
                  session: {
                    ...current.session,
                    media: {
                      ...current.session.media,
                      preview_status: state.status,
                      preview_error: state.error,
                    },
                  },
                }
              : {},
          );
        }
      } catch (error) {
        if (!cancelled) commands.handleError(error);
      }
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api, commands, store, mediaPlayable, previewStatus]);

  // beforeunload guard while a draft is dirty or a save is in flight.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const state = store.getState();
      if (state.dirty || state.saveState === "saving") event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [store]);

  const session = useAppSelector((state) => state.session);
  const banner = useAppSelector((state) => state.banner);
  const toast = useAppSelector((state) => state.toast);
  const helpOpen = useAppSelector((state) => state.helpOpen);
  const listWidth = useAppSelector((state) => state.prefs.listWidth);
  const editorWidth = useAppSelector((state) => state.prefs.editorWidth);

  if (!session) {
    return (
      <div className="loading-screen">
        <LoaderCircle className="loading-spinner" />
        <h1>OpenBBQ Review</h1>
        <p>{banner?.text ?? t("app.loading")}</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <TopBar />
      {banner && (
        <div className={`message-banner ${banner.danger ? "danger" : ""}`}>
          <span>{banner.text}</span>
          <Button size="sm" variant="outline" onClick={() => void commands.reloadDiscard()}>
            <RotateCcw /> {t("app.reloadDiscard")}
          </Button>
        </div>
      )}
      <div className="workbench">
        <aside className="list-pane" style={{ width: listWidth }} aria-label={t("app.cueList")}>
          <CueListPanel />
        </aside>
        <Resizer side="list" />
        <section className="center-pane" aria-label={t("app.mediaTimeline")}>
          <CompletionBanner />
          <PlayerPanel />
        </section>
        <Resizer side="editor" />
        <aside className="editor-pane" style={{ width: editorWidth }} aria-label={t("app.editor")}>
          <CueEditor />
        </aside>
      </div>
      <TimelineDock />
      <DeleteDialog />
      <AddTermDialog />
      {helpOpen && <ShortcutHelp />}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}

function DeleteDialog() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const open = useAppSelector((state) => state.deleteOpen);
  const selectedId = useAppSelector((state) => state.selectedId);
  return (
    <AlertDialog open={open} onOpenChange={(next) => store.setState({ deleteOpen: next })}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("action.delete")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("error.deleteConfirm", { id: selectedId ?? "" })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={() => store.setState({ deleteOpen: false })}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              store.setState({ deleteOpen: false });
              void commands.deleteSelected();
            }}
          >
            {t("action.delete")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
