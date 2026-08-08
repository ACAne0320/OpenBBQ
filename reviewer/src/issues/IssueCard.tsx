import { Check, CircleX, Plus } from "lucide-react";
import type { CueIssue } from "../api/types";
import { useI18n } from "../app/i18n";
import { useServices } from "../app/services";
import { KIND_ICONS, issueTone } from "./IssueBadge";
import { issueText } from "./issue-messages";

/**
 * Inline issue card for the selected cue (§7). Cards reflect the store only —
 * rule issues disappear on the next save's recomputed snapshot; dismissed
 * ones render collapsed with the resolved (green) treatment.
 */
export function IssueCard({ issue }: { issue: CueIssue }) {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const Icon = KIND_ICONS[issue.kind];
  const tone = issueTone(issue);

  if (issue.dismissed) {
    return (
      <div className="issue-card resolved" data-kind={issue.kind}>
        <Check aria-hidden="true" />
        <span className="issue-card-message">{issueText(issue, t)}</span>
        <span className="issue-card-dismissed">{t("issue.dismissed")}</span>
      </div>
    );
  }

  return (
    <div className={`issue-card ${tone}`} data-kind={issue.kind}>
      <span className={`issue-badge ${tone}`}>
        <Icon aria-hidden="true" />
      </span>
      <span className="issue-card-message">{issueText(issue, t)}</span>
      <span className="issue-card-actions">
        {issue.kind === "term" && (
          <button
            className="issue-card-action"
            onClick={() => {
              const actual = typeof issue.detail.term === "string" ? issue.detail.term : "";
              const expected =
                typeof issue.detail.expected === "string" ? issue.detail.expected : "";
              store.setState({ addTerm: { source: actual, target: expected, note: "" } });
            }}
          >
            <Plus aria-hidden="true" />
            {t("issue.addTerm")}
          </button>
        )}
        <button
          className="issue-card-action"
          aria-label={t("issue.dismiss")}
          onClick={() => void commands.dismissIssue(issue.cue_id, issue.kind)}
        >
          <CircleX aria-hidden="true" />
          {t("issue.dismiss")}
        </button>
      </span>
    </div>
  );
}
