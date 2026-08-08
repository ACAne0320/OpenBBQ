import type { CueIssue } from "../api/types";
import type { MessageKey } from "../app/i18n";

export type IssueDescription =
  | { key: MessageKey; values: Record<string, string | number> }
  | { raw: string };

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

/**
 * Localized issue description built from kind + detail (the server's English
 * `message` is only a fallback, e.g. for free-text agent notes).
 */
export function describeIssue(issue: CueIssue): IssueDescription {
  const detail = issue.detail;
  switch (issue.kind) {
    case "term":
      return {
        key: "issue.msg.term",
        values: {
          term: text(detail.term),
          expected: text(detail.expected),
        },
      };
    case "timing": {
      if ("cps" in detail) {
        return {
          key: "issue.msg.timingCps",
          values: { cps: num(detail.cps), max: num(detail.max_cps) },
        };
      }
      const duration = num(detail.duration);
      const min = num(detail.min_duration);
      const max = num(detail.max_duration);
      return duration < min
        ? { key: "issue.msg.timingShort", values: { duration, min } }
        : { key: "issue.msg.timingLong", values: { duration, max } };
    }
    case "budget":
      return {
        key: "issue.msg.budget",
        values: { used: num(detail.used), limit: num(detail.limit) },
      };
    case "asr_confidence": {
      const words = Array.isArray(detail.words)
        ? detail.words
            .map((entry) =>
              typeof entry === "object" && entry !== null
                ? text((entry as Record<string, unknown>).word)
                : "",
            )
            .filter(Boolean)
            .join(", ")
        : "";
      return { key: "issue.msg.asr", values: { words } };
    }
    default:
      return { raw: issue.message };
  }
}

export function issueText(issue: CueIssue, t: (key: MessageKey, values?: Record<string, string | number>) => string): string {
  const description = describeIssue(issue);
  return "raw" in description ? description.raw : t(description.key, description.values);
}
