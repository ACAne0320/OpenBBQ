import { Check, CircleAlert, Sparkles, X } from "lucide-react";
import type { Cue, Suggestion } from "../api/types";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { selectSelectedCue } from "../store/selectors";
import { contentHashForCue } from "./content-hash";

/**
 * Pending suggestion card (§7, purple/agent): message + clickable patch
 * preview (fills the draft, no mutation), accept (one atomic write), reject
 * (no confirm). Content drift only shows the stale hint — never blocks.
 */
export function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const { t } = useI18n();
  const { commands } = useServices();
  const cue = useAppSelector(selectSelectedCue);
  const includeTarget = useAppSelector((state) => state.session?.target_lang != null);

  const stale = cue ? isStale(suggestion, cue, includeTarget) : false;
  const patch = suggestion.patch;
  const proposedText = patch.target ?? patch.source ?? null;

  return (
    <div className="suggestion-card" data-suggestion={suggestion.id}>
      <div className="suggestion-card-head">
        <span className="issue-badge agent">
          <Sparkles aria-hidden="true" />
        </span>
        <span className="issue-card-message">{suggestion.message}</span>
      </div>
      {proposedText != null && (
        <button
          className="suggestion-patch"
          title={t("suggestion.fill")}
          onClick={() => commands.applySuggestionToDraft(suggestion)}
        >
          {proposedText}
        </button>
      )}
      {(patch.start != null || patch.end != null) && (
        <button
          className="suggestion-patch time"
          title={t("suggestion.fill")}
          onClick={() => commands.applySuggestionToDraft(suggestion)}
        >
          {formatPatchTime(patch.start)} – {formatPatchTime(patch.end)}
        </button>
      )}
      {stale && (
        <div className="suggestion-stale">
          <CircleAlert aria-hidden="true" />
          {t("suggestion.stale")}
        </div>
      )}
      <div className="suggestion-card-actions">
        <button
          className="suggestion-accept"
          onClick={() => void commands.acceptSuggestion(suggestion.id)}
        >
          <Check aria-hidden="true" />
          {t("suggestion.accept")}
        </button>
        <button
          className="suggestion-reject"
          onClick={() => void commands.rejectSuggestion(suggestion.id)}
        >
          <X aria-hidden="true" />
          {t("suggestion.reject")}
        </button>
      </div>
    </div>
  );
}

function isStale(suggestion: Suggestion, cue: Cue, includeTarget: boolean): boolean {
  return contentHashForCue(cue, includeTarget) !== suggestion.content_hash;
}

function formatPatchTime(value: number | null | undefined): string {
  return value == null ? "…" : value.toFixed(3);
}
