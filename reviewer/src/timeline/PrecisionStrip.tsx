import { SkipBack, SkipForward } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { IconButton } from "@/components/icon-button";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { updatePrefs } from "../store/prefs";
import { selectSelectedCue } from "../store/selectors";
import { formatTimeInput } from "../editor/time-format";

const NUDGE_STEPS = [0.01, 0.05, 0.1, 0.5];

function formatDuration(seconds: number) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}

/** Frame-accurate strip under the timeline: IN/OUT nudges, duration, step. */
export function PrecisionStrip() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const cue = useAppSelector(selectSelectedCue);
  const draft = useAppSelector((state) => state.draft);
  const nudgeStep = useAppSelector((state) => state.prefs.nudgeStep);

  if (!cue || !draft) return null;
  return (
    <div className="precision-strip">
      <div
        className="precision-cue"
        aria-label={`${t("timeline.selectedCue")} #${cue.id}`}
        title={t("timeline.selectedCue")}
      >
        <strong>#{cue.id}</strong>
      </div>
      <TimeNudge
        label={t("timeline.start")}
        compactLabel={t("timeline.in")}
        value={draft.start}
        earlierLabel={t("timeline.nudgeStartEarlier")}
        laterLabel={t("timeline.nudgeStartLater")}
        onEarlier={() => commands.nudgeSelected("start", -1)}
        onLater={() => commands.nudgeSelected("start", 1)}
      />
      <TimeNudge
        label={t("timeline.end")}
        compactLabel={t("timeline.out")}
        value={draft.end}
        earlierLabel={t("timeline.nudgeEndEarlier")}
        laterLabel={t("timeline.nudgeEndLater")}
        onEarlier={() => commands.nudgeSelected("end", -1)}
        onLater={() => commands.nudgeSelected("end", 1)}
      />
      <div
        className="precision-duration"
        aria-label={`${t("timeline.duration")} ${formatDuration(draft.end - draft.start)}`}
        title={t("timeline.duration")}
      >
        <strong>{formatDuration(draft.end - draft.start)}</strong>
      </div>
      <Select
        value={String(nudgeStep)}
        onValueChange={(value) => value && updatePrefs(store, { nudgeStep: Number(value) })}
      >
        <SelectTrigger className="nudge-step-select" size="sm" aria-label={t("timeline.step")}>
          <SelectValue>{Math.round(nudgeStep * 1000)}ms</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {NUDGE_STEPS.map((step) => (
            <SelectItem key={step} value={String(step)}>
              {Math.round(step * 1000)} ms
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="body-nudge">
        <IconButton
          size="icon-xs"
          label={t("timeline.nudgeEarlier")}
          onClick={() => commands.nudgeSelected("body", -1)}
        >
          <SkipBack />
        </IconButton>
        <IconButton
          size="icon-xs"
          label={t("timeline.nudgeLater")}
          onClick={() => commands.nudgeSelected("body", 1)}
        >
          <SkipForward />
        </IconButton>
      </div>
    </div>
  );
}

function TimeNudge({
  label,
  compactLabel,
  value,
  earlierLabel,
  laterLabel,
  onEarlier,
  onLater,
}: {
  label: string;
  compactLabel: string;
  value: number;
  earlierLabel: string;
  laterLabel: string;
  onEarlier: () => void;
  onLater: () => void;
}) {
  return (
    <div className="time-nudge" role="group" aria-label={label} title={label}>
      <span aria-hidden="true">{compactLabel}</span>
      <IconButton size="icon-xs" label={earlierLabel} onClick={onEarlier}>
        <SkipBack />
      </IconButton>
      <strong>{formatTimeInput(value)}</strong>
      <IconButton size="icon-xs" label={laterLabel} onClick={onLater}>
        <SkipForward />
      </IconButton>
    </div>
  );
}
