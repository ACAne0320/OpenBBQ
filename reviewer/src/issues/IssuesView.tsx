import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Undo2 } from "lucide-react";
import type { Cue, CueIssue, IssueKind, Suggestion } from "../api/types";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { KIND_ICONS, issueTone } from "./IssueBadge";
import { issueText } from "./issue-messages";

const KIND_ORDER: IssueKind[] = ["term", "timing", "budget", "asr_confidence", "agent_note"];

interface OpenEntry {
  cue: Cue;
  issue: CueIssue;
}

interface ProcessedEntry {
  key: string;
  cueId: number;
  /** Dismissed rule issue (message derived from kind+detail). */
  issue?: CueIssue;
  /** Resolved suggestion (server message; rejected ones offer reopen). */
  message?: string;
  reopenId?: string;
}

export interface IssueGroup {
  kind: IssueKind;
  open: OpenEntry[];
  processed: ProcessedEntry[];
}

function knownKind(kind: string): IssueKind {
  return (KIND_ORDER as string[]).includes(kind) ? (kind as IssueKind) : "agent_note";
}

/** Groups cue issues + resolved suggestions by kind for the issues view. */
export function groupIssues(cues: Cue[], suggestions: Suggestion[]): IssueGroup[] {
  const groups = new Map<IssueKind, IssueGroup>();
  for (const kind of KIND_ORDER) groups.set(kind, { kind, open: [], processed: [] });
  for (const cue of cues) {
    for (const issue of cue.issues) {
      const group = groups.get(issue.kind);
      if (!group) continue;
      if (issue.dismissed) {
        group.processed.push({
          key: `dismissed-${cue.id}-${issue.kind}-${group.processed.length}`,
          cueId: cue.id,
          issue,
        });
      } else {
        group.open.push({ cue, issue });
      }
    }
  }
  for (const suggestion of suggestions) {
    if (suggestion.status === "pending") continue;
    const group = groups.get(knownKind(suggestion.kind));
    if (!group) continue;
    group.processed.push({
      key: `suggestion-${suggestion.id}`,
      cueId: suggestion.cue_id,
      message: suggestion.message,
      ...(suggestion.status === "rejected" ? { reopenId: suggestion.id } : {}),
    });
  }
  return [...groups.values()].filter(
    (group) => group.open.length > 0 || group.processed.length > 0,
  );
}

/** Left-column issues view (§7): kind groups, cue jump, processed audit. */
export function IssuesView() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const cues = useAppSelector((state) => state.cues);
  const suggestions = useAppSelector((state) => state.suggestions);
  const processedExpanded = useAppSelector((state) => state.processedExpanded);
  const [collapsed, setCollapsed] = useState<Partial<Record<IssueKind, boolean>>>({});

  const groups = groupIssues(cues, suggestions);
  if (groups.length === 0) {
    return <div className="empty-state">{t("issues.empty")}</div>;
  }

  return (
    <div className="issues-view">
      {groups.map((group) => {
        const Icon = KIND_ICONS[group.kind];
        const tone = group.open[0] ? issueTone(group.open[0].issue) : "info";
        const isCollapsed = collapsed[group.kind] ?? false;
        const processedOpen = processedExpanded[group.kind] ?? false;
        return (
          <section className="issue-group" key={group.kind}>
            <button
              className="issue-group-head"
              aria-expanded={!isCollapsed}
              onClick={() =>
                setCollapsed((current) => ({ ...current, [group.kind]: !isCollapsed }))
              }
            >
              {isCollapsed ? <ChevronRight /> : <ChevronDown />}
              <span className={`issue-badge ${tone}`}>
                <Icon aria-hidden="true" />
              </span>
              <strong>{t(`issue.kind.${group.kind}`)}</strong>
              <span className="issue-group-count">
                {t("issues.cueCount", { count: group.open.length })}
              </span>
            </button>
            {!isCollapsed && (
              <div className="issue-group-body">
                {group.open.map(({ cue, issue }, index) => (
                  <button
                    className="issue-entry"
                    key={`${cue.id}-${issue.kind}-${index}`}
                    onClick={() => void commands.selectCueById(cue.id)}
                  >
                    <strong>#{cue.id}</strong>
                    <span>{issueText(issue, t)}</span>
                  </button>
                ))}
                {group.processed.length > 0 && (
                  <div className="issue-processed">
                    <button
                      className="issue-processed-head"
                      aria-expanded={processedOpen}
                      onClick={() =>
                        store.setState((state) => ({
                          processedExpanded: {
                            ...state.processedExpanded,
                            [group.kind]: !processedOpen,
                          },
                        }))
                      }
                    >
                      {processedOpen ? <ChevronDown /> : <ChevronRight />}
                      <Check aria-hidden="true" />
                      <span>
                        {t("issues.processed")} ({group.processed.length})
                      </span>
                    </button>
                    {processedOpen &&
                      group.processed.map((entry) => (
                        <div className="issue-entry processed" key={entry.key}>
                          <strong>#{entry.cueId}</strong>
                          <span>
                            {entry.issue ? issueText(entry.issue, t) : entry.message}
                          </span>
                          {entry.reopenId && (
                            <button
                              className="issue-reopen"
                              onClick={(event) => {
                                event.stopPropagation();
                                void commands.reopenSuggestion(entry.reopenId!);
                              }}
                            >
                              <Undo2 aria-hidden="true" />
                              {t("issues.reopen")}
                            </button>
                          )}
                        </div>
                      ))}
                  </div>
                )}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
