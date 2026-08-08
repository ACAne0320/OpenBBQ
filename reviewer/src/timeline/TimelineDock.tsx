import { Focus, Magnet, Maximize2, Minimize2, Repeat2, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback } from "react";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { IconButton } from "@/components/icon-button";
import type { TimedWord } from "../api/types";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { useTheme } from "../app/theme";
import { updatePrefs } from "../store/prefs";
import { fitCueZoom, MAX_TIMELINE_ZOOM } from "./timeline-model";
import { EditToolbar } from "./EditToolbar";
import { PrecisionStrip } from "./PrecisionStrip";
import { Timeline } from "./Timeline";

/**
 * Full-width dock at the bottom (design §6.1): edit toolbar, timeline toolbar,
 * the canvas timeline, and the precision strip. The container isolates the
 * `currentTime` subscription so only the canvas subtree sees timeupdate ticks.
 */
export function TimelineDock() {
  const { t } = useI18n();
  const { resolvedTheme } = useTheme();
  const { store, player, commands } = useServices();
  const cues = useAppSelector((state) => state.cues);
  const selectedId = useAppSelector((state) => state.selectedId);
  const duration = useAppSelector((state) => state.session?.media.duration ?? 0);
  const zoom = useAppSelector((state) => state.prefs.zoom);
  const large = useAppSelector((state) => state.prefs.largeTimeline);
  const snap = useAppSelector((state) => state.prefs.snap);
  const isPlaying = useAppSelector((state) => state.isPlaying);
  const currentTime = useAppSelector((state) => state.currentTime);
  const onWordsLoaded = useCallback(
    (words: TimedWord[], range: { start: number; end: number }) => {
      store.setState({ transcriptWords: words, wordsRange: range });
    },
    [store],
  );

  return (
    <footer className="timeline-dock">
      <EditToolbar />
      <TimelineToolbar />
      <Timeline
        cues={cues}
        currentTime={currentTime}
        duration={duration}
        selectedId={selectedId}
        zoom={zoom}
        large={large}
        snapEnabled={snap}
        theme={resolvedTheme}
        ariaLabel={t("timeline.aria")}
        isPlaying={isPlaying}
        getPlaybackTime={() => player.getPlaybackTime()}
        onSeek={(time) => player.seek(time)}
        onSelect={(id) => void commands.selectCueById(id)}
        onTimeChange={async (id, start, end) => {
          await commands.setCueTime(id, start, end);
        }}
        onWordsLoaded={onWordsLoaded}
      />
      <PrecisionStrip />
    </footer>
  );
}

function TimelineToolbar() {
  const { t } = useI18n();
  const { store, player } = useServices();
  const zoom = useAppSelector((state) => state.prefs.zoom);
  const large = useAppSelector((state) => state.prefs.largeTimeline);
  const snap = useAppSelector((state) => state.prefs.snap);
  const loopCue = useAppSelector((state) => state.prefs.loopCue);
  const draft = useAppSelector((state) => state.draft);
  const duration = useAppSelector((state) => state.session?.media.duration ?? 0);

  const zoomOutStep = () => Math.max(1, zoom - (zoom <= 8 ? 0.5 : zoom <= 24 ? 2 : 8));
  const zoomInStep = () => Math.min(MAX_TIMELINE_ZOOM, zoom + (zoom < 8 ? 0.5 : zoom < 24 ? 2 : 8));

  return (
    <div className="timeline-toolbar">
      <div className="timeline-heading">
        <strong>{t("timeline.title")}</strong>
        <span>{t("timeline.hint")}</span>
      </div>
      <div className="snap-control" title={snap ? t("timeline.snapOn") : t("timeline.snapOff")}>
        <Magnet />
        <Switch
          size="sm"
          checked={snap}
          aria-label={snap ? t("timeline.snapOn") : t("timeline.snapOff")}
          onCheckedChange={(checked) => updatePrefs(store, { snap: checked })}
        />
      </div>
      <IconButton
        label={t("transport.loop")}
        variant={loopCue ? "secondary" : "ghost"}
        onClick={() => updatePrefs(store, { loopCue: !loopCue })}
      >
        <Repeat2 />
      </IconButton>
      <IconButton label={t("timeline.zoomOut")} disabled={zoom <= 1} onClick={() => updatePrefs(store, { zoom: zoomOutStep() })}>
        <ZoomOut />
      </IconButton>
      <Slider
        className="zoom-slider"
        min={1}
        max={MAX_TIMELINE_ZOOM}
        step={0.5}
        value={[zoom]}
        onValueChange={(value) =>
          updatePrefs(store, { zoom: Array.isArray(value) ? (value[0] ?? 1) : value })
        }
        aria-label={t("timeline.title")}
      />
      <span className="zoom-value">{zoom.toFixed(1)}×</span>
      <IconButton
        label={t("timeline.zoomIn")}
        disabled={zoom >= MAX_TIMELINE_ZOOM}
        onClick={() => updatePrefs(store, { zoom: zoomInStep() })}
      >
        <ZoomIn />
      </IconButton>
      <IconButton
        label={t("timeline.fitCue")}
        disabled={!draft}
        onClick={() => {
          const current = store.getState().draft;
          if (!current) return;
          updatePrefs(store, {
            zoom: fitCueZoom(duration, { start: current.start, end: current.end }),
          });
          player.seek((current.start + current.end) / 2);
        }}
      >
        <Focus />
      </IconButton>
      <IconButton
        label={large ? t("timeline.collapse") : t("timeline.expand")}
        onClick={() => updatePrefs(store, { largeTimeline: !large })}
      >
        {large ? <Minimize2 /> : <Maximize2 />}
      </IconButton>
    </div>
  );
}
