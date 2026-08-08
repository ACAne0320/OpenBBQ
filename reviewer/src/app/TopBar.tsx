import { CheckCircle2, CircleAlert, Languages, LoaderCircle, Moon, Sun } from "lucide-react";
import { IconButton } from "@/components/icon-button";
import { useI18n, type MessageKey } from "./i18n";
import { useAppSelector } from "./services";
import { useTheme } from "./theme";
import type { SaveState } from "../store/state";

const SAVE_ICONS: Record<SaveState, typeof CheckCircle2> = {
  saved: CheckCircle2,
  saving: LoaderCircle,
  failed: CircleAlert,
  conflict: CircleAlert,
};

const SAVE_LABELS: Record<SaveState, MessageKey> = {
  saved: "app.saved",
  saving: "app.saving",
  failed: "app.saveFailed",
  conflict: "app.conflict",
};

export function TopBar() {
  const { locale, setLocale, t } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const session = useAppSelector((state) => state.session);
  const saveState = useAppSelector((state) => state.saveState);
  if (!session) return null;
  const SaveIcon = SAVE_ICONS[saveState];
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-copy">
          <strong>OpenBBQ Review</strong>
          <span className="brand-subtitle" title={session.workspace}>
            {session.title}
          </span>
        </div>
      </div>
      <div className="topbar-actions">
        <IconButton
          label={locale === "en" ? t("app.localeChinese") : t("app.localeEnglish")}
          onClick={() => setLocale(locale === "en" ? "zh" : "en")}
        >
          <Languages />
        </IconButton>
        <IconButton
          label={resolvedTheme === "dark" ? t("app.themeLight") : t("app.themeDark")}
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {resolvedTheme === "dark" ? <Sun /> : <Moon />}
        </IconButton>
        <div className={`save-indicator ${saveState}`} role="status">
          <SaveIcon />
          <span>{t(SAVE_LABELS[saveState])}</span>
        </div>
        <div className="progress-summary">
          <strong>
            {t("app.progress", {
              reviewed: session.progress.reviewed,
              total: session.progress.total,
            })}
          </strong>
          {session.progress.flagged > 0 && (
            <span>{t("app.flaggedProgress", { count: session.progress.flagged })}</span>
          )}
        </div>
      </div>
    </header>
  );
}
