import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n, type MessageKey } from "./i18n";
import { useServices } from "./services";
import { SHORTCUT_SECTIONS, SHORTCUTS, type ShortcutSection } from "./shortcuts";

const SECTION_LABELS: Record<ShortcutSection, MessageKey> = {
  transport: "shortcut.section.transport",
  editing: "shortcut.section.editing",
  cues: "shortcut.section.cues",
  tools: "shortcut.section.tools",
};

/**
 * Shortcut help overlay (§5.5/§7): renders straight from the SHORTCUTS
 * table, so the help can never drift from the actual bindings.
 */
export function ShortcutHelp() {
  const { t } = useI18n();
  const { store } = useServices();
  const close = () => store.setState({ helpOpen: false });

  return (
    <div className="help-backdrop" role="presentation" onClick={close}>
      <div
        className="help-overlay"
        role="dialog"
        aria-modal="true"
        aria-label={t("help.title")}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="help-head">
          <strong>{t("help.title")}</strong>
          <Button size="icon-sm" variant="ghost" aria-label={t("help.close")} onClick={close}>
            <X />
          </Button>
        </div>
        <div className="help-body">
          {SHORTCUT_SECTIONS.map((section) => {
            const entries = SHORTCUTS.filter((shortcut) => shortcut.section === section);
            if (entries.length === 0) return null;
            return (
              <section className="help-section" key={section}>
                <h3>{t(SECTION_LABELS[section])}</h3>
                <dl>
                  {entries.map((shortcut) => (
                    <div className="help-row" key={shortcut.id}>
                      <dt>
                        <kbd>{shortcut.keys}</kbd>
                      </dt>
                      <dd>{t(shortcut.descriptionKey)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
