import { describe, expect, it } from "vitest";
import type { CueIssue } from "../api/types";
import { describeIssue } from "./issue-messages";

function issue(kind: CueIssue["kind"], detail: Record<string, unknown>): CueIssue {
  return {
    cue_id: 1,
    kind,
    severity: "warning",
    message: "server message",
    detail,
    source: "rule",
    dismissed: false,
    suggestion_ids: [],
  };
}

describe("describeIssue", () => {
  it("builds the term message from expected/actual", () => {
    expect(describeIssue(issue("term", { term: "LLM", expected: "大语言模型" }))).toEqual({
      key: "issue.msg.term",
      values: { term: "LLM", expected: "大语言模型" },
    });
  });

  it("distinguishes short/long duration timing issues", () => {
    expect(
      describeIssue(issue("timing", { duration: 0.3, min_duration: 0.5, max_duration: 7 })),
    ).toEqual({ key: "issue.msg.timingShort", values: { duration: 0.3, min: 0.5 } });
    expect(
      describeIssue(issue("timing", { duration: 9, min_duration: 0.5, max_duration: 7 })),
    ).toEqual({ key: "issue.msg.timingLong", values: { duration: 9, max: 7 } });
  });

  it("builds the cps timing message", () => {
    expect(describeIssue(issue("timing", { cps: 24.5, max_cps: 20 }))).toEqual({
      key: "issue.msg.timingCps",
      values: { cps: 24.5, max: 20 },
    });
  });

  it("builds the budget message from used/limit", () => {
    expect(describeIssue(issue("budget", { used: 42, limit: 30 }))).toEqual({
      key: "issue.msg.budget",
      values: { used: 42, limit: 30 },
    });
  });

  it("joins low-confidence ASR words", () => {
    expect(
      describeIssue(
        issue("asr_confidence", {
          words: [
            { word: "frieren", prob: 0.3 },
            { word: "zeltra", prob: 0.41 },
          ],
          threshold: 0.5,
        }),
      ),
    ).toEqual({ key: "issue.msg.asr", values: { words: "frieren, zeltra" } });
  });

  it("falls back to the server message for agent notes", () => {
    const agent = { ...issue("agent_note", {}), source: "agent" as const, message: "agent text" };
    expect(describeIssue(agent)).toEqual({ raw: "agent text" });
  });
});
