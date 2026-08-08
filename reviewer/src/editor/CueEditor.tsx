import { useState } from "react";
import { BookMarked, Captions, Check, CircleAlert, Flag, MessageSquareText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { IconButton } from "@/components/icon-button";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { StatusIcon } from "../cues/StatusIcon";
import { IssueCard } from "../issues/IssueCard";
import { SuggestionCard } from "../issues/SuggestionCard";
import { selectBudgetUsage, selectSelectedCue } from "../store/selectors";
import { TimeInput } from "./TimeInput";

function languageName(language: string, locale: "en" | "zh") {
  try {
    return new Intl.DisplayNames([locale], { type: "language" }).of(language) ?? language;
  } catch {
    return language;
  }
}

function formatDuration(seconds: number) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}

interface TextSelection {
  field: "source" | "target";
  text: string;
}

/** Editor zone (design §6.1/§7): text fields, times, issue + suggestion cards. */
export function CueEditor() {
  const { t, locale } = useI18n();
  const { commands, store } = useServices();
  const cue = useAppSelector(selectSelectedCue);
  const draft = useAppSelector((state) => state.draft);
  const session = useAppSelector((state) => state.session);
  const showNote = useAppSelector((state) => state.showNote);
  const budget = useAppSelector(selectBudgetUsage);
  const pendingSuggestions = useAppSelector((state) => {
    const selectedId = state.selectedId;
    return state.suggestions.filter(
      (suggestion) => suggestion.cue_id === selectedId && suggestion.status === "pending",
    );
  }, shallowArrayEqual);
  const [textSelection, setTextSelection] = useState<TextSelection | null>(null);

  if (!cue || !draft || !session) {
    return <div className="cue-editor-empty" />;
  }

  const trackSelection = (field: TextSelection["field"], element: HTMLTextAreaElement) => {
    const selected = element.value.slice(element.selectionStart, element.selectionEnd).trim();
    setTextSelection(selected ? { field, text: selected } : null);
  };

  const launchAddTerm = () => {
    if (!textSelection) return;
    store.setState({
      addTerm: {
        source: textSelection.field === "source" ? textSelection.text : "",
        target: textSelection.field === "target" ? textSelection.text : "",
        note: "",
      },
    });
    setTextSelection(null);
  };

  const targetId = `target-${cue.id}`;
  return (
    <section className="cue-editor" aria-label={`${t("timeline.selectedCue")} #${cue.id}`}>
      <div className="editor-header">
        <div>
          <StatusIcon status={cue.status} />
          <strong>#{cue.id}</strong>
          <span>{t(`cue.status.${cue.status}`)}</span>
        </div>
        <div className="metric-row">
          <span>{formatDuration(draft.end - draft.start)}</span>
          <span>{t("cue.sourceCps", { value: cue.source_cps })}</span>
          {budget && <span className={budget.over ? "budget-over" : undefined}>
            {t("cue.budget", { used: budget.used, limit: budget.limit })}
          </span>}
          <IconButton
            size="icon-xs"
            label={t("cue.note")}
            variant={showNote || draft.note ? "secondary" : "ghost"}
            onClick={() => store.setState((state) => ({ showNote: !state.showNote }))}
          >
            <MessageSquareText />
          </IconButton>
        </div>
      </div>
      <label className="editor-field">
        <span>{t("cue.source")}</span>
        <span className="editor-field-body">
          <Textarea
            ref={(node) => {
              commands.editorRefs.source = node;
            }}
            value={draft.source}
            rows={2}
            onChange={(event) => commands.updateDraft({ source: event.target.value })}
            onSelect={(event) => trackSelection("source", event.currentTarget)}
          />
          {textSelection?.field === "source" && (
            <button className="selection-term-action" onClick={launchAddTerm}>
              <BookMarked aria-hidden="true" />
              {t("glossary.fromSelection")}
            </button>
          )}
        </span>
      </label>
      <div className="editor-field translation-field">
        <div className="translation-field-header">
          <label htmlFor={targetId}>{t("cue.translationField")}</label>
          <Select
            value={session.target_lang ?? "source"}
            onValueChange={(value) => value && void commands.switchLanguage(String(value))}
          >
            <SelectTrigger
              className="editor-language-select"
              size="sm"
              aria-label={t("app.reviewLanguage")}
            >
              <Captions aria-hidden="true" />
              <SelectValue>
                {session.target_lang ? languageName(session.target_lang, locale) : t("app.sourceOnly")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="source">{t("app.sourceOnly")}</SelectItem>
              {session.languages.map((language) => (
                <SelectItem key={language} value={language}>
                  {languageName(language, locale)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {session.target_lang ? (
          <span className="editor-field-body">
            <Textarea
              id={targetId}
              ref={(node) => {
                commands.editorRefs.target = node;
              }}
              value={draft.target}
              rows={2}
              aria-label={t("cue.translation", { language: session.target_lang })}
              onChange={(event) => commands.updateDraft({ target: event.target.value })}
              onSelect={(event) => trackSelection("target", event.currentTarget)}
            />
            {textSelection?.field === "target" && (
              <button className="selection-term-action" onClick={launchAddTerm}>
                <BookMarked aria-hidden="true" />
                {t("glossary.fromSelection")}
              </button>
            )}
          </span>
        ) : (
          <p className="source-only-hint">{t("cue.sourceOnlyHint")}</p>
        )}
      </div>
      <div className="time-inputs">
        <TimeInput
          label={t("timeline.start")}
          value={draft.start}
          validate={(seconds) => seconds < draft.end}
          onCommit={(seconds) => commands.updateDraft({ start: seconds })}
        />
        <TimeInput
          label={t("timeline.end")}
          value={draft.end}
          validate={(seconds) => draft.start < seconds}
          onCommit={(seconds) => commands.updateDraft({ end: seconds })}
        />
      </div>
      {budget?.over && (
        <div className="validation-warning">
          <CircleAlert />
          {t("cue.overBudget")}
        </div>
      )}
      {cue.issues.length > 0 && (
        <div className="issue-card-list">
          {cue.issues.map((issue, index) => (
            <IssueCard key={`${issue.kind}-${index}`} issue={issue} />
          ))}
        </div>
      )}
      {pendingSuggestions.length > 0 && (
        <div className="suggestion-card-list">
          {pendingSuggestions.map((suggestion) => (
            <SuggestionCard key={suggestion.id} suggestion={suggestion} />
          ))}
        </div>
      )}
      {showNote && (
        <label className="editor-field note-field">
          <span>{t("cue.note")}</span>
          <Input
            type="text"
            value={draft.note}
            placeholder={t("cue.notePlaceholder")}
            onChange={(event) => commands.updateDraft({ note: event.target.value })}
          />
        </label>
      )}
      <div className="review-actions">
        <Button onClick={() => void commands.mark("reviewed")}>
          <Check />
          {t("action.review")}
          <kbd>Enter</kbd>
        </Button>
        <Button variant="outline" onClick={() => void commands.mark("flagged")}>
          <Flag />
          {t("action.flag")}
          <kbd>⇧F</kbd>
        </Button>
      </div>
    </section>
  );
}

function shallowArrayEqual(a: unknown[], b: unknown[]): boolean {
  return a.length === b.length && a.every((entry, index) => Object.is(entry, b[index]));
}
