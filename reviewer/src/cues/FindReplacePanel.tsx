import { useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "../api/client";
import type { BatchMatch } from "../api/types";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import type { BatchReplaceParams } from "../commands/commands";

type Field = "source" | "target";

/**
 * Find/replace panel (§7): forced dry-run preview with highlighted matches
 * before execute; the whole batch lands as one undo. Any field change
 * invalidates the preview, so execute can never run blind.
 */
export function FindReplacePanel() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const selection = useAppSelector((state) => state.selection);
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [fields, setFields] = useState<Field[]>(["source", "target"]);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [regex, setRegex] = useState(false);
  const [scope, setScope] = useState<"all" | "selection">("all");
  const [preview, setPreview] = useState<BatchMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const invalidate = () => {
    setPreview(null);
    setError(null);
  };

  const toggleField = (field: Field) => {
    invalidate();
    setFields((current) =>
      current.includes(field)
        ? current.filter((entry) => entry !== field)
        : [...current, field],
    );
  };

  const params = (): BatchReplaceParams => ({
    find,
    replace,
    fields,
    caseSensitive,
    regex,
    ...(scope === "selection" && selection.length > 1 ? { cueIds: selection } : {}),
  });

  const matchCount = preview?.reduce((total, match) => total + match.spans.length, 0) ?? 0;

  const runPreview = async () => {
    if (!find || fields.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await commands.previewBatchReplace(params());
      setPreview(result.matches);
    } catch (cause) {
      setPreview(null);
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  const runExecute = async () => {
    if (!preview || matchCount === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await commands.executeBatchReplace(params());
      if (response) store.setState({ findOpen: false });
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  const describeError = (cause: unknown): string => {
    if (cause instanceof ApiError) {
      const detail = cause.payload.detail ? String(cause.payload.detail) : "";
      if (cause.payload.error === "invalid_regex") {
        return t("find.invalidRegex", { detail });
      }
      return `${String(cause.payload.error ?? cause.message)}${detail ? `: ${detail}` : ""}`;
    }
    return cause instanceof Error ? cause.message : t("error.unknown");
  };

  return (
    <div className="find-panel" role="dialog" aria-label={t("find.title")}>
      <div className="find-head">
        <strong>{t("find.title")}</strong>
        <button
          className="find-close"
          aria-label={t("find.close")}
          onClick={() => store.setState({ findOpen: false })}
        >
          <X aria-hidden="true" />
        </button>
      </div>
      <div className="find-fields">
        <Input
          value={find}
          aria-label={t("find.find")}
          placeholder={t("find.find")}
          autoFocus
          onChange={(event) => {
            setFind(event.target.value);
            invalidate();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void runPreview();
            }
          }}
        />
        <Input
          value={replace}
          aria-label={t("find.replace")}
          placeholder={t("find.replace")}
          onChange={(event) => {
            setReplace(event.target.value);
            invalidate();
          }}
        />
      </div>
      <div className="find-options">
        <label>
          <input
            type="checkbox"
            checked={fields.includes("source")}
            onChange={() => toggleField("source")}
          />
          {t("find.scopeSource")}
        </label>
        <label>
          <input
            type="checkbox"
            checked={fields.includes("target")}
            onChange={() => toggleField("target")}
          />
          {t("find.scopeTarget")}
        </label>
        <label>
          <input
            type="checkbox"
            checked={caseSensitive}
            onChange={(event) => {
              setCaseSensitive(event.target.checked);
              invalidate();
            }}
          />
          {t("find.caseSensitive")}
        </label>
        <label>
          <input
            type="checkbox"
            checked={regex}
            onChange={(event) => {
              setRegex(event.target.checked);
              invalidate();
            }}
          />
          {t("find.regex")}
        </label>
      </div>
      <div className="find-options">
        <label>
          <input
            type="radio"
            name="find-scope"
            checked={scope === "all"}
            onChange={() => {
              setScope("all");
              invalidate();
            }}
          />
          {t("find.scopeAll")}
        </label>
        <label className={selection.length <= 1 ? "disabled" : undefined}>
          <input
            type="radio"
            name="find-scope"
            disabled={selection.length <= 1}
            checked={scope === "selection" && selection.length > 1}
            onChange={() => {
              setScope("selection");
              invalidate();
            }}
          />
          {t("find.scopeSelection", { count: selection.length })}
        </label>
      </div>
      {error && <div className="find-error">{error}</div>}
      {fields.length === 0 && <div className="find-error">{t("find.needsField")}</div>}
      {preview && (
        <div className="find-matches">
          <div className="find-matches-count">
            {matchCount > 0 ? t("find.matches", { count: matchCount }) : t("find.noMatches")}
          </div>
          {preview.map((match, index) => (
            <div className="find-match" key={`${match.cue_id}-${match.field}-${index}`}>
              <strong>#{match.cue_id}</strong>
              <span className="find-match-field">
                {match.field === "source" ? t("find.scopeSource") : t("find.scopeTarget")}
              </span>
              <span className="find-match-text">{highlightSpans(match)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="find-actions">
        <Button
          size="sm"
          variant="outline"
          disabled={!find || fields.length === 0 || busy}
          onClick={() => void runPreview()}
        >
          {t("find.preview")}
        </Button>
        <Button
          size="sm"
          disabled={!preview || matchCount === 0 || busy}
          onClick={() => void runExecute()}
        >
          {t("find.execute", { count: matchCount })}
        </Button>
      </div>
    </div>
  );
}

/** Renders the matched field text with <mark> over each reported span. */
export function highlightSpans(match: BatchMatch): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  const spans = [...match.spans].sort((a, b) => a[0] - b[0]);
  spans.forEach(([start, end], index) => {
    if (start > cursor) nodes.push(match.text.slice(cursor, start));
    nodes.push(<mark key={index}>{match.text.slice(start, end)}</mark>);
    cursor = end;
  });
  if (cursor < match.text.length) nodes.push(match.text.slice(cursor));
  return nodes;
}
