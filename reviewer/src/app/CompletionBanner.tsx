import { useState } from "react";
import { CheckCircle2, ClipboardCopy, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "./i18n";
import { useAppSelector, useServices } from "./services";
import { selectIssueCounts } from "../store/selectors";

/** Canonical next-step export command handed over to the CLI. */
export function exportCommand(workspace: string, targetLang: string | null): string {
  const base = `openbbq export --workspace ${workspace}`;
  return targetLang ? `${base} --to ${targetLang} --mode bilingual` : base;
}

/**
 * Completion state (§7): restrained banner once every cue is reviewed —
 * progress, remaining open items, one-click copy of the export command.
 * Dismissible; the services watcher re-arms it after leaving complete.
 */
export function CompletionBanner() {
  const { t } = useI18n();
  const { store } = useServices();
  const progress = useAppSelector((state) => state.progress);
  const dismissed = useAppSelector((state) => state.completedDismissed);
  const issueCounts = useAppSelector(selectIssueCounts);
  const pendingSuggestions = useAppSelector(
    (state) => state.suggestions.filter((suggestion) => suggestion.status === "pending").length,
  );
  const session = useAppSelector((state) => state.session);
  const [copied, setCopied] = useState(false);

  const complete = progress.total > 0 && progress.reviewed === progress.total;
  if (!complete || dismissed || !session) return null;

  const openItems = issueCounts.total + pendingSuggestions;
  const command = exportCommand(session.workspace, session.target_lang);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
    } catch {
      // Fallback for environments without async clipboard.
      const area = document.createElement("textarea");
      area.value = command;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="completion-banner" role="status">
      <CheckCircle2 aria-hidden="true" />
      <div className="completion-copy">
        <strong>{t("complete.title")}</strong>
        <span>
          {openItems > 0 ? t("complete.remaining", { count: openItems }) : t("complete.clean")}
        </span>
      </div>
      <code className="completion-command">{command}</code>
      <Button size="sm" variant="outline" onClick={() => void copy()}>
        <ClipboardCopy />
        {copied ? t("complete.copied") : t("complete.copy")}
      </Button>
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={t("complete.dismiss")}
        onClick={() => store.setState({ completedDismissed: true })}
      >
        <X />
      </Button>
    </div>
  );
}
