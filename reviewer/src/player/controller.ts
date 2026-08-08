import { updatePrefs } from "../store/prefs";
import type { AppStore } from "../store/state";

/**
 * Imperative boundary between the media element and the store. The element
 * itself never lives in React state; the panel registers it here, and all
 * transport actions (shortcuts, buttons, timeline seeks) go through this
 * controller so there is exactly one writer for playback state.
 */
export class PlayerController {
  private media: HTMLMediaElement | null = null;
  private fullscreenToggle: (() => void) | null = null;
  private noticeTimer: number | null = null;

  constructor(private store: AppStore) {}

  attach(element: HTMLMediaElement | null): void {
    this.media = element;
    if (!element) return;
    const state = this.store.getState();
    if (Math.abs(element.currentTime - state.currentTime) > 0.05) {
      element.currentTime = state.currentTime;
    }
    element.volume = state.prefs.volume;
    element.muted = state.prefs.muted;
    element.playbackRate = state.prefs.playbackRate;
  }

  getPlaybackTime(): number {
    return this.media?.currentTime ?? this.store.getState().currentTime;
  }

  getDuration(): number {
    return (
      this.media?.duration || this.store.getState().session?.media.duration || 0
    );
  }

  seek(time: number): void {
    const clamped = Math.max(0, Math.min(this.getDuration(), time));
    this.store.setState({ currentTime: clamped });
    if (this.media) this.media.currentTime = clamped;
  }

  togglePlay(): void {
    const media = this.media;
    if (!media) return;
    if (media.paused) void media.play();
    else media.pause();
  }

  play(): void {
    if (this.media) void this.media.play();
  }

  pause(): void {
    this.media?.pause();
  }

  setVolume(volume: number): void {
    const normalized = Math.max(0, Math.min(1, volume));
    if (this.media) {
      this.media.volume = normalized;
      this.media.muted = false;
    }
    updatePrefs(this.store, { volume: normalized, muted: false });
  }

  toggleMute(): void {
    const muted = !this.store.getState().prefs.muted;
    if (this.media) this.media.muted = muted;
    updatePrefs(this.store, { muted });
  }

  setPlaybackRate(rate: number): void {
    if (this.media) this.media.playbackRate = rate;
    updatePrefs(this.store, { playbackRate: rate });
  }

  registerFullscreenToggle(toggle: (() => void) | null): void {
    this.fullscreenToggle = toggle;
  }

  toggleFullscreen(): void {
    this.fullscreenToggle?.();
  }

  handleTimeUpdate(element: HTMLMediaElement): void {
    const state = this.store.getState();
    let time = element.currentTime;
    const selected = state.cues.find((cue) => cue.id === state.selectedId) ?? null;
    if (state.prefs.loopCue && selected && time >= selected.end) {
      element.currentTime = selected.start;
      time = selected.start;
    }
    this.store.setState({ currentTime: time });
  }

  setPlaying(isPlaying: boolean): void {
    if (this.store.getState().isPlaying !== isPlaying) this.store.setState({ isPlaying });
  }

  showNotice(notice: string | null, duration = 700): void {
    if (this.noticeTimer != null) window.clearTimeout(this.noticeTimer);
    this.noticeTimer = null;
    this.store.setState({ playbackNotice: notice });
    if (notice != null) {
      this.noticeTimer = window.setTimeout(() => {
        this.noticeTimer = null;
        this.store.setState({ playbackNotice: null });
      }, duration);
    }
  }
}
