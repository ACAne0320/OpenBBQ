import { AudioLines, BookMarked, Ruler, Sparkles, Timer, type LucideIcon } from "lucide-react";
import type { CueIssue, IssueKind } from "../api/types";
import { useI18n } from "../app/i18n";
import { cueIssueKinds } from "../store/selectors";

/**
 * Issue visual language (design §6.2): icon encodes kind, color encodes
 * source/severity — amber for rule warnings, blue for info, purple for agent.
 * No emoji anywhere.
 */
export const KIND_ICONS: Record<IssueKind, LucideIcon> = {
  term: BookMarked,
  timing: Timer,
  budget: Ruler,
  asr_confidence: AudioLines,
  agent_note: Sparkles,
};

export function issueTone(issue: CueIssue): "warning" | "info" | "agent" {
  if (issue.source === "agent") return "agent";
  return issue.severity === "warning" ? "warning" : "info";
}

export function IssueBadge({ issue }: { issue: CueIssue }) {
  const { t } = useI18n();
  const Icon = KIND_ICONS[issue.kind] ?? Sparkles;
  const label = t(`issue.kind.${issue.kind}`);
  return (
    <span
      className={`issue-badge ${issueTone(issue)}`}
      title={label}
      aria-label={label}
      role="img"
    >
      <Icon aria-hidden="true" />
    </span>
  );
}

/** One badge per distinct non-dismissed issue kind on the cue. */
export function IssueBadges({ issues }: { issues: CueIssue[] }) {
  const kinds = cueIssueKinds(issues);
  if (kinds.length === 0) return null;
  return (
    <span className="issue-badges">
      {kinds.map((issue) => (
        <IssueBadge key={issue.kind} issue={issue} />
      ))}
    </span>
  );
}
