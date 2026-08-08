import { useCallback, useEffect, useRef } from "react";
import {
  AudioWaveform,
  Captions,
  LoaderCircle,
  Maximize,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { IconButton } from "@/components/icon-button";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { updatePrefs } from "../store/prefs";
import { selectOverlayCue } from "../store/selectors";
import type { OverlayMode } from "../store/state";

function formatPlayerTime(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

/** Center zone: media stage, subtitle overlay, persistent transport controls. */
export function PlayerPanel() {
  const { t } = useI18n();
  const { store, player, commands, api } = useServices();
  const session = useAppSelector((state) => state.session);
  const overlay = useAppSelector((state) => state.prefs.overlay);
  const overlayCue = useAppSelector(selectOverlayCue);
  const notice = useAppSelector((state) => state.playbackNotice);
  const panelRef = useRef<HTMLDivElement>(null);

  const startBrowserPreview = useCallback(async () => {
    try {
      const state = await api.startPreview();
      store.setState((current) =>
        current.session
          ? {
              session: {
                ...current.session,
                media: {
                  ...current.session.media,
                  playable: state.status === "ready",
                  preview_status: state.status,
                  preview_error: state.error,
                },
              },
            }
          : {},
      );
    } catch (error) {
      commands.handleError(error);
    }
  }, [store, commands, api]);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    void panelRef.current?.requestFullscreen();
  }, []);

  useEffect(() => {
    player.registerFullscreenToggle(toggleFullscreen);
    return () => player.registerFullscreenToggle(null);
  }, [player, toggleFullscreen]);

  if (!session) return null;
  const { media } = session;

  return (
    <div className="media-panel" ref={panelRef}>
      {media.kind === "video" && media.playable ? (
        <video
          ref={(node) => player.attach(node)}
          src={media.url}
          preload="metadata"
          tabIndex={0}
          aria-label={media.name}
          onClick={() => player.togglePlay()}
          onError={() => void startBrowserPreview()}
          onTimeUpdate={(event) => player.handleTimeUpdate(event.currentTarget)}
          onPlay={() => player.setPlaying(true)}
          onPause={() => player.setPlaying(false)}
          onRateChange={(event) => updatePrefs(store, { playbackRate: event.currentTarget.playbackRate })}
          onVolumeChange={(event) =>
            updatePrefs(store, {
              volume: event.currentTarget.volume,
              muted: event.currentTarget.muted,
            })
          }
        />
      ) : media.kind === "audio" && media.playable ? (
        <div className="audio-stage">
          <AudioWaveform className="audio-icon" aria-hidden="true" />
          <strong>{t("app.audio")}</strong>
          <audio
            ref={(node) => player.attach(node)}
            src={media.url}
            preload="metadata"
            onTimeUpdate={(event) => player.handleTimeUpdate(event.currentTarget)}
            onPlay={() => player.setPlaying(true)}
            onPause={() => player.setPlaying(false)}
            onRateChange={(event) =>
              updatePrefs(store, { playbackRate: event.currentTarget.playbackRate })
            }
            onVolumeChange={(event) =>
              updatePrefs(store, {
                volume: event.currentTarget.volume,
                muted: event.currentTarget.muted,
              })
            }
          />
        </div>
      ) : (
        <div className="proxy-stage">
          <LoaderCircle className="loading-spinner" />
          <strong>{t("app.proxyTitle")}</strong>
          <p>{t("app.proxyDescription")}</p>
          <span>
            {media.preview_status === "building" ? t("app.transcoding") : media.preview_status}
          </span>
          {media.preview_error && <code>{media.preview_error}</code>}
          {media.preview_status === "failed" && (
            <Button variant="outline" onClick={() => void startBrowserPreview()}>
              <RotateCcw /> {t("app.retryProxy")}
            </Button>
          )}
        </div>
      )}
      {overlay !== "hidden" && overlayCue && (
        <div className="subtitle-overlay" aria-live="polite">
          {(overlay === "bilingual" || overlay === "target") && overlayCue.target && (
            <div className="target-line">{overlayCue.target}</div>
          )}
          {(overlay === "bilingual" || overlay === "source") && (
            <div className="source-line">{overlayCue.source}</div>
          )}
        </div>
      )}
      {notice && (
        <div className="playback-notice" role="status" aria-live="polite">
          {notice}
        </div>
      )}
      {media.playable && <PlayerControls />}
    </div>
  );
}

function PlayerControls() {
  const { t } = useI18n();
  const { store, player } = useServices();
  const isPlaying = useAppSelector((state) => state.isPlaying);
  const overlay = useAppSelector((state) => state.prefs.overlay);
  const playbackRate = useAppSelector((state) => state.prefs.playbackRate);
  const volume = useAppSelector((state) => state.prefs.volume);
  const muted = useAppSelector((state) => state.prefs.muted);

  const changeVolumeFromPointer = (element: HTMLElement, clientY: number) => {
    const bounds = element.getBoundingClientRect();
    if (bounds.height <= 0) return;
    player.setVolume(1 - (clientY - bounds.top) / bounds.height);
  };

  return (
    <div className="player-controls" role="group" aria-label={t("transport.controls")}>
      <ProgressSlider />
      <div className="player-control-row">
        <div className="player-control-cluster">
          <IconButton
            className="play-button"
            label={isPlaying ? t("transport.pause") : t("transport.play")}
            shortcut="Space"
            onClick={() => player.togglePlay()}
          >
            {isPlaying ? <Pause /> : <Play />}
          </IconButton>
          <IconButton
            label={t("transport.skipBack")}
            shortcut="←"
            onClick={() => player.seek(player.getPlaybackTime() - 5)}
          >
            <SkipBack />
          </IconButton>
          <IconButton
            label={t("transport.skipForward")}
            shortcut="→"
            onClick={() => player.seek(player.getPlaybackTime() + 5)}
          >
            <SkipForward />
          </IconButton>
          <Timecode />
        </div>
        <div className="player-control-cluster player-control-cluster-end">
          <div className="volume-control">
            <Button
              className="volume-button"
              size="icon"
              variant="ghost"
              aria-label={muted ? t("transport.unmute") : t("transport.mute")}
              onClick={() => player.toggleMute()}
            >
              {muted || volume === 0 ? <VolumeX /> : <Volume2 />}
            </Button>
            <div className="volume-popover">
              <output>{Math.round((muted ? 0 : volume) * 100)}</output>
              <div
                className="volume-range-shell"
                role="slider"
                tabIndex={0}
                aria-label={t("transport.volume")}
                aria-orientation="vertical"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((muted ? 0 : volume) * 100)}
                onPointerDown={(event) => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  changeVolumeFromPointer(event.currentTarget, event.clientY);
                }}
                onPointerMove={(event) => {
                  if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                    changeVolumeFromPointer(event.currentTarget, event.clientY);
                  }
                }}
                onPointerUp={(event) => {
                  event.currentTarget.releasePointerCapture(event.pointerId);
                  event.currentTarget.blur();
                }}
                onKeyDown={(event) => {
                  if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
                  event.preventDefault();
                  event.stopPropagation();
                  player.setVolume((muted ? 0 : volume) + (event.key === "ArrowUp" ? 0.05 : -0.05));
                }}
              >
                <span className="volume-track" />
                <span
                  className="volume-fill"
                  style={{ height: `${(muted ? 0 : volume) * 100}%` }}
                />
                <span
                  className="volume-thumb"
                  style={{ bottom: `${(muted ? 0 : volume) * 100}%` }}
                />
              </div>
            </div>
          </div>
          <div className="speed-control">
            <Button
              className="speed-button"
              size="sm"
              variant="ghost"
              aria-label={t("transport.speed")}
              aria-haspopup="menu"
            >
              {playbackRate}×
            </Button>
            <div className="speed-popover" role="menu" aria-label={t("transport.speed")}>
              {[2, 1.5, 1.25, 1, 0.75, 0.5].map((rate) => (
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={playbackRate === rate}
                  className={playbackRate === rate ? "active" : undefined}
                  key={rate}
                  onClick={(event) => {
                    player.setPlaybackRate(rate);
                    event.currentTarget.blur();
                  }}
                >
                  {rate}×
                </button>
              ))}
            </div>
          </div>
          <Select
            value={overlay}
            onValueChange={(value) => value && updatePrefs(store, { overlay: value as OverlayMode })}
          >
            <SelectTrigger
              className="player-select subtitle-select"
              size="sm"
              aria-label={t("transport.subtitles")}
            >
              <Captions />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bilingual">{t("overlay.bilingual")}</SelectItem>
              <SelectItem value="target">{t("overlay.target")}</SelectItem>
              <SelectItem value="source">{t("overlay.source")}</SelectItem>
              <SelectItem value="hidden">{t("overlay.hidden")}</SelectItem>
            </SelectContent>
          </Select>
          <IconButton
            label={t("transport.fullscreen")}
            shortcut="F"
            onClick={() => player.toggleFullscreen()}
          >
            <Maximize />
          </IconButton>
        </div>
      </div>
    </div>
  );
}

/** Isolated subscription: only this subtree re-renders at timeupdate rate. */
function ProgressSlider() {
  const { t } = useI18n();
  const { player } = useServices();
  const currentTime = useAppSelector((state) => state.currentTime);
  const duration = useAppSelector((state) => state.session?.media.duration ?? 0);
  return (
    <Slider
      className="player-progress"
      min={0}
      max={duration}
      step={0.01}
      value={[Math.min(currentTime, duration)]}
      onValueChange={(value) => player.seek(Array.isArray(value) ? (value[0] ?? 0) : value)}
      aria-label={t("transport.progress")}
    />
  );
}

function Timecode() {
  const currentTime = useAppSelector((state) => state.currentTime);
  const duration = useAppSelector((state) => state.session?.media.duration ?? 0);
  return (
    <span className="timecode">
      {formatPlayerTime(currentTime)} <span>/ {formatPlayerTime(duration)}</span>
    </span>
  );
}
