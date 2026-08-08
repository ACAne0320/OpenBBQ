import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { useI18n } from "../app/i18n";
import { formatTimeInput, parseTimeInput } from "./time-format";

interface TimeInputProps {
  label: string;
  value: number;
  /** Extra validation (e.g. start<end); return true to accept the value. */
  validate: (seconds: number) => boolean;
  onCommit: (seconds: number) => void;
}

/**
 * Formatted MM:SS.mmm time input. Invalid text is rejected with an inline
 * hint and the display reverts — no draft update, so no save command fires.
 */
export function TimeInput({ label, value, validate, onCommit }: TimeInputProps) {
  const { t } = useI18n();
  const [text, setText] = useState(() => formatTimeInput(value));
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-sync from the prop only when the prop itself changes; editing
  // transitions (commit/revert) set the text explicitly.
  useEffect(() => {
    if (!editing) setText(formatTimeInput(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const revert = () => {
    setText(formatTimeInput(value));
    setEditing(false);
  };

  const commit = () => {
    const parsed = parseTimeInput(text);
    if (parsed == null) {
      setError(t("cue.timeInvalid"));
      revert();
      return;
    }
    if (!validate(parsed)) {
      setError(t("cue.timeOrder"));
      revert();
      return;
    }
    setError(null);
    setEditing(false);
    setText(formatTimeInput(parsed));
    if (parsed !== value) onCommit(parsed);
  };

  return (
    <label className={`time-input ${error ? "invalid" : ""}`}>
      <span>{label}</span>
      <Input
        value={text}
        aria-label={label}
        aria-invalid={error != null}
        inputMode="decimal"
        onFocus={() => {
          setEditing(true);
          setError(null);
        }}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            setError(null);
            revert();
          }
        }}
      />
      {error && <em className="time-input-hint">{error}</em>}
    </label>
  );
}
