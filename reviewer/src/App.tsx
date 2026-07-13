import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AudioWaveform,
  Captions,
  Check,
  CheckCircle2,
  Circle,
  CircleAlert,
  Combine,
  Filter,
  Flag,
  Focus,
  Languages,
  LoaderCircle,
  LocateFixed,
  Magnet,
  Maximize,
  Maximize2,
  MessageSquareText,
  Minimize2,
  Moon,
  Pause,
  Play,
  Plus,
  Redo2,
  Repeat2,
  RotateCcw,
  Scissors,
  Search,
  SkipBack,
  SkipForward,
  Sun,
  Trash2,
  Undo2,
  Volume2,
  VolumeX,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { IconButton } from "@/components/icon-button";
import { ApiError, api, authenticateFromFragment, opId } from "./api";
import { useI18n } from "./i18n";
import { Timeline } from "./Timeline";
import {
  cueMovementBounds,
  fitCueZoom,
  MAX_TIMELINE_ZOOM,
  nudgeCueRange,
  type NudgeTarget,
} from "./timeline-model";
import { useTheme } from "./theme";
import type { Cue, CueResponse, ReviewStatus, Session } from "./types";

type SaveState = "saved" | "saving" | "failed" | "conflict";
type Filter =
  | "all"
  | ReviewStatus
  | "missing"
  | "over_budget"
  | "time_warning"
  | "term_warning";
type Overlay = "bilingual" | "source" | "target" | "hidden";

interface Draft {
  source: string;
  target: string;
  start: number;
  end: number;
  note: string;
}

interface ArrowHold {
  key: "ArrowLeft" | "ArrowRight";
  timer: number;
  interval: number | null;
  long: boolean;
  previousRate: number;
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    Boolean(
      target.closest(
        "input, textarea, select, button, a[href], [contenteditable='true'], [role='button'], [role='slider'], [role='switch'], [role='combobox'], [role='menuitem'], [role='menuitemradio'], [role='option']",
      ),
    )
  );
}

export function App() {
  const { locale, setLocale, t } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const [session, setSession] = useState<Session | null>(null);
  const [cues, setCues] = useState<Cue[]>([]);
  const [revision, setRevision] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [message, setMessage] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("unreviewed");
  const [search, setSearch] = useState("");
  const [overlay, setOverlay] = useState<Overlay>("bilingual");
  const [zoom, setZoom] = useState(1);
  const [largeTimeline, setLargeTimeline] = useState(false);
  const [loopCue, setLoopCue] = useState(false);
  const [follow, setFollow] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [playbackNotice, setPlaybackNotice] = useState<string | null>(null);
  const [snapEnabled, setSnapEnabled] = useState(true);
  const [nudgeStep, setNudgeStep] = useState(0.1);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [showNote, setShowNote] = useState(false);
  const mediaRef = useRef<HTMLMediaElement>(null);
  const currentTimeRef = useRef(0);
  const mediaPanelRef = useRef<HTMLDivElement>(null);
  const arrowHoldRef = useRef<ArrowHold | null>(null);
  const sourceRef = useRef<HTMLTextAreaElement>(null);
  const targetRef = useRef<HTMLTextAreaElement>(null);
  const selectedCardRef = useRef<HTMLElement>(null);
  const savePromise = useRef<Promise<string> | null>(null);
  const playbackNoticeTimer = useRef<number | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const dirtyRef = useRef(false);
  const selectedIdRef = useRef<number | null>(null);
  const revisionRef = useRef("");
  const cuesRef = useRef<Cue[]>([]);
  const targetLangRef = useRef<string | null>(null);

  revisionRef.current = revision;
  cuesRef.current = cues;
  targetLangRef.current = session?.target_lang ?? null;

  const selectCueId = useCallback((cueId: number | null) => {
    selectedIdRef.current = cueId;
    setSelectedId(cueId);
  }, []);

  const updateDraft = useCallback((changes: Partial<Draft>) => {
    const current = draftRef.current;
    if (!current) return;
    const next = { ...current, ...changes };
    draftRef.current = next;
    dirtyRef.current = true;
    setDraft(next);
    setDirty(true);
    setSaveState((current) => (current === "failed" ? "saving" : current));
  }, []);

  const selectedCue = cues.find((cue) => cue.id === selectedId) ?? null;
  const activeCue = cues.find((cue) => currentTime >= cue.start && currentTime <= cue.end) ?? null;

  const load = useCallback(async () => {
    try {
      await authenticateFromFragment();
      const [nextSession, cueResponse] = await Promise.all([api.session(), api.cues()]);
      const initialCue =
        cueResponse.cues.find((cue) => cue.status === "unreviewed") ?? cueResponse.cues[0] ?? null;
      draftRef.current = null;
      dirtyRef.current = false;
      setDraft(null);
      setDirty(false);
      setShowNote(false);
      setSession(nextSession);
      setCues(cueResponse.cues);
      setRevision(cueResponse.revision);
      revisionRef.current = cueResponse.revision;
      cuesRef.current = cueResponse.cues;
      targetLangRef.current = nextSession.target_lang;
      selectCueId(initialCue?.id ?? null);
      if (initialCue) {
        currentTimeRef.current = initialCue.start;
        setCurrentTime(initialCue.start);
        setZoom(fitCueZoom(nextSession.media.duration, initialCue));
      }
      setSaveState("saved");
      setMessage(null);
    } catch (error) {
      handleError(error);
    }
  }, [selectCueId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!session || session.media.playable || session.media.preview_status === "failed") return;
    let cancelled = false;
    if (session.media.preview_status === "needed") void api.startPreview().catch(handleError);
    const timer = window.setInterval(async () => {
      try {
        const state = await api.previewStatus();
        if (cancelled) return;
        if (state.status === "ready") {
          window.clearInterval(timer);
          setSession(await api.session());
        } else {
          setSession((current) =>
            current
              ? {
                  ...current,
                  media: {
                    ...current.media,
                    preview_status: state.status,
                    preview_error: state.error,
                  },
                }
              : current,
          );
        }
      } catch (error) {
        if (!cancelled) handleError(error);
      }
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session?.media.playable, session?.media.preview_status]);

  useEffect(() => {
    if (!selectedCue || dirty) return;
    setShowNote(false);
    const nextDraft = {
      source: selectedCue.source,
      target: selectedCue.target ?? "",
      start: selectedCue.start,
      end: selectedCue.end,
      note: selectedCue.note ?? "",
    };
    draftRef.current = nextDraft;
    dirtyRef.current = false;
    setDraft(nextDraft);
  }, [selectedCue, selectedId, dirty]);

  useEffect(() => {
    if (
      !dirty ||
      !draft ||
      selectedId == null ||
      saveState === "conflict" ||
      saveState === "failed"
    ) return;
    const timer = window.setTimeout(() => {
      void persistDraft().catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [dirty, draft, selectedId, revision, saveState]);

  useEffect(() => {
    if (follow && selectedCardRef.current) {
      selectedCardRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedId, follow]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty || saveState === "saving") event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, saveState]);

  useEffect(
    () => () => {
      if (playbackNoticeTimer.current != null) window.clearTimeout(playbackNoticeTimer.current);
    },
    [],
  );

  const applyResponse = useCallback((response: CueResponse, markClean = !dirtyRef.current) => {
    revisionRef.current = response.revision;
    cuesRef.current = response.cues;
    setRevision(response.revision);
    setCues(response.cues);
    setSession((current) => (current ? { ...current, progress: response.progress } : current));
    if (markClean) {
      dirtyRef.current = false;
      setDirty(false);
      setSaveState("saved");
    } else {
      setSaveState("saving");
    }
    setMessage(null);
  }, []);

  const persistDraft = useCallback(async (): Promise<string> => {
    if (savePromise.current) return savePromise.current;
    const promise = (async () => {
      while (dirtyRef.current) {
        const draftSnapshot = draftRef.current;
        const cueId = selectedIdRef.current;
        if (!draftSnapshot || cueId == null) return revisionRef.current;
        const cueSnapshot = cuesRef.current.find((cue) => cue.id === cueId) ?? null;
        const contentChanged =
          cueSnapshot == null ||
          draftSnapshot.source !== cueSnapshot.source ||
          draftSnapshot.target !== (cueSnapshot.target ?? "") ||
          draftSnapshot.start !== cueSnapshot.start ||
          draftSnapshot.end !== cueSnapshot.end;
        const noteChanged = draftSnapshot.note !== (cueSnapshot?.note ?? "");
        if (!contentChanged && !noteChanged) {
          dirtyRef.current = false;
          setDirty(false);
          setSaveState("saved");
          return revisionRef.current;
        }
        setSaveState("saving");
        let response = contentChanged
          ? await api.updateCue(cueId, {
              base_revision: revisionRef.current,
              op_id: opId("edit"),
              source: draftSnapshot.source,
              ...(targetLangRef.current ? { target: draftSnapshot.target } : {}),
              start: Number(draftSnapshot.start.toFixed(3)),
              end: Number(draftSnapshot.end.toFixed(3)),
            })
          : await api.setStatus(cueId, {
              base_revision: revisionRef.current,
              op_id: opId("note"),
              status: cueSnapshot?.status ?? "unreviewed",
              note: draftSnapshot.note || null,
            });
        if (contentChanged && noteChanged) {
          response = await api.setStatus(cueId, {
            base_revision: response.revision,
            op_id: opId("note"),
            status: "unreviewed",
            note: draftSnapshot.note || null,
          });
        }
        const hasNewerDraft =
          draftRef.current !== draftSnapshot || selectedIdRef.current !== cueId;
        applyResponse(response, !hasNewerDraft);
        if (!hasNewerDraft) return response.revision;
      }
      return revisionRef.current;
    })()
      .catch((error) => {
        handleError(error);
        throw error;
      })
      .finally(() => {
        savePromise.current = null;
      });
    savePromise.current = promise;
    return promise;
  }, [applyResponse]);

  const runMutation = useCallback(
    async (operation: (baseRevision: string) => Promise<CueResponse>) => {
      try {
        const base = await persistDraft();
        setSaveState("saving");
        const response = await operation(base);
        applyResponse(response);
        return response;
      } catch (error) {
        handleError(error);
        return null;
      }
    },
    [persistDraft, applyResponse],
  );

  const seek = useCallback((time: number) => {
    currentTimeRef.current = time;
    setCurrentTime(time);
    if (mediaRef.current) mediaRef.current.currentTime = time;
  }, []);

  const attachMedia = useCallback((node: HTMLMediaElement | null) => {
    mediaRef.current = node;
    if (node && Math.abs(node.currentTime - currentTimeRef.current) > 0.05) {
      node.currentTime = currentTimeRef.current;
    }
  }, []);

  const getPlaybackTime = useCallback(
    () => mediaRef.current?.currentTime ?? currentTimeRef.current,
    [],
  );

  const mark = useCallback(
    async (status: ReviewStatus) => {
      if (selectedId == null) return;
      const response = await runMutation((base) =>
        api.setStatus(selectedId, {
          base_revision: base,
          op_id: opId(`status-${status}`),
          status,
          note: draft?.note || null,
        }),
      );
      if (response && status === "reviewed") {
        const index = response.cues.findIndex((cue) => cue.id === selectedId);
        const next = [...response.cues.slice(index + 1), ...response.cues.slice(0, index)].find(
          (cue) => cue.status === "unreviewed",
        );
        if (next) {
          selectCueId(next.id);
          seek(next.start);
        }
      }
    },
    [selectedId, draft?.note, runMutation, seek, selectCueId],
  );

  const saveAndNext = useCallback(async () => {
    if (selectedId == null) return;
    try {
      await persistDraft();
      const index = cues.findIndex((cue) => cue.id === selectedId);
      const next = [...cues.slice(index + 1), ...cues.slice(0, Math.max(0, index))].find(
        (cue) => cue.status === "unreviewed",
      );
      if (next) {
        selectCueId(next.id);
        seek(next.start);
      }
    } catch {
      // The visible save banner keeps the current draft recoverable.
    }
  }, [cues, persistDraft, selectedId, seek, selectCueId]);

  const selectCue = useCallback(
    async (cue: Cue) => {
      try {
        await persistDraft();
        selectCueId(cue.id);
        dirtyRef.current = false;
        setDirty(false);
        seek(cue.start);
      } catch {
        // The conflict banner preserves the unsaved draft.
      }
    },
    [persistDraft, seek, selectCueId],
  );

  const updateTimeline = useCallback(
    async (cueId: number, start: number, end: number) => {
      await runMutation((base) =>
        api.updateCue(cueId, {
          base_revision: base,
          op_id: opId("timeline"),
          start,
          end,
        }),
      );
    },
    [runMutation],
  );

  const splitCurrent = useCallback(async () => {
    if (!selectedCue || !draft || currentTime <= selectedCue.start || currentTime >= selectedCue.end) {
      setMessage(t("error.split"));
      return;
    }
    const ratio = (currentTime - selectedCue.start) / selectedCue.duration;
    const sourceIndex = sourceRef.current?.selectionStart ?? Math.round(draft.source.length * ratio);
    const targetIndex = targetRef.current?.selectionStart ?? Math.round(draft.target.length * ratio);
    const response = await runMutation((base) =>
      api.split(selectedCue.id, {
        base_revision: base,
        op_id: opId("split"),
        at: currentTime,
        source_left: draft.source.slice(0, sourceIndex).trim(),
        source_right: draft.source.slice(sourceIndex).trim(),
        target_left: session?.target_lang ? draft.target.slice(0, targetIndex).trim() : null,
        target_right: session?.target_lang ? draft.target.slice(targetIndex).trim() : null,
      }),
    );
    if (response?.changed[1]) selectCueId(response.changed[1]);
  }, [selectedCue, draft, currentTime, session?.target_lang, runMutation, selectCueId, t]);

  const mergeNext = useCallback(async () => {
    if (!selectedCue) return;
    const index = cues.findIndex((cue) => cue.id === selectedCue.id);
    const next = cues[index + 1];
    if (!next) return;
    await runMutation((base) =>
      api.merge({
        base_revision: base,
        op_id: opId("merge"),
        cue_ids: [selectedCue.id, next.id],
      }),
    );
  }, [selectedCue, cues, runMutation]);

  const insertAtPlayhead = useCallback(async () => {
    const response = await runMutation((base) =>
      api.insert({ base_revision: base, op_id: opId("insert"), at: currentTime }),
    );
    if (response?.changed[0]) selectCueId(response.changed[0]);
  }, [currentTime, runMutation, selectCueId]);

  const deleteCurrent = useCallback(async () => {
    if (!selectedCue) return;
    const index = cues.findIndex((cue) => cue.id === selectedCue.id);
    const response = await runMutation((base) =>
      api.deleteCue(selectedCue.id, { base_revision: base, op_id: opId("delete") }),
    );
    if (response) selectCueId(response.cues[Math.min(index, response.cues.length - 1)]?.id ?? null);
  }, [selectedCue, cues, runMutation, selectCueId]);

  const undo = useCallback(async () => {
    await runMutation((base) => api.undo({ base_revision: base, op_id: opId("undo") }));
  }, [runMutation]);

  const redo = useCallback(async () => {
    await runMutation((base) => api.redo({ base_revision: base, op_id: opId("redo") }));
  }, [runMutation]);

  const switchLanguage = async (value: string) => {
    try {
      const base = await persistDraft();
      const response = await api.switchTarget({
        base_revision: base,
        op_id: opId("switch"),
        target_lang: value === "source" ? null : value,
      });
      setSession(response);
      applyResponse(response);
      targetLangRef.current = response.target_lang;
      selectCueId(response.cues.find((cue) => cue.status === "unreviewed")?.id ?? response.cues[0]?.id ?? null);
    } catch (error) {
      handleError(error);
    }
  };

  const togglePlayback = useCallback(() => {
    const media = mediaRef.current;
    if (!media) return;
    if (media.paused) void media.play();
    else media.pause();
  }, []);

  const startBrowserPreview = useCallback(async () => {
    try {
      const state = await api.startPreview();
      setSession((current) =>
        current
          ? {
              ...current,
              media: {
                ...current.media,
                playable: state.status === "ready",
                preview_status: state.status,
                preview_error: state.error,
              },
            }
          : current,
      );
    } catch (error) {
      handleError(error);
    }
  }, []);

  const changeVolume = useCallback((nextVolume: number) => {
    const normalized = Math.max(0, Math.min(1, nextVolume));
    const media = mediaRef.current;
    if (media) {
      media.volume = normalized;
      media.muted = false;
    }
    setVolume(normalized);
    setMuted(false);
  }, []);

  const changeVolumeFromPointer = useCallback(
    (element: HTMLElement, clientY: number) => {
      const bounds = element.getBoundingClientRect();
      if (bounds.height <= 0) return;
      changeVolume(1 - (clientY - bounds.top) / bounds.height);
    },
    [changeVolume],
  );

  const toggleMute = useCallback(() => {
    const media = mediaRef.current;
    if (!media) return;
    media.muted = !media.muted;
    setMuted(media.muted);
  }, []);

  const changePlaybackRate = useCallback((nextRate: number) => {
    if (mediaRef.current) mediaRef.current.playbackRate = nextRate;
    setPlaybackRate(nextRate);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    void mediaPanelRef.current?.requestFullscreen();
  }, []);

  const showPlaybackNotice = useCallback((notice: string, duration = 700) => {
    if (playbackNoticeTimer.current != null) window.clearTimeout(playbackNoticeTimer.current);
    setPlaybackNotice(notice);
    playbackNoticeTimer.current = window.setTimeout(() => {
      setPlaybackNotice(null);
      playbackNoticeTimer.current = null;
    }, duration);
  }, []);

  const nudgeSelected = useCallback(
    (target: NudgeTarget, direction: -1 | 1) => {
      if (!draft || !session) return;
      const next = nudgeCueRange(
        { start: draft.start, end: draft.end },
        target,
        nudgeStep * direction,
        session.media.duration,
        (() => {
          const index = cues.findIndex((cue) => cue.id === selectedId);
          return cueMovementBounds(cues, index, session.media.duration);
        })(),
      );
      updateDraft(next);
    },
    [cues, draft, nudgeStep, selectedId, session, updateDraft],
  );

  const handleMediaTime = useCallback(
    (media: HTMLMediaElement) => {
      currentTimeRef.current = media.currentTime;
      setCurrentTime(media.currentTime);
      if (loopCue && selectedCue && media.currentTime >= selectedCue.end) media.currentTime = selectedCue.start;
    },
    [loopCue, selectedCue],
  );

  useEffect(() => {
    if (!follow || dirty || !activeCue || activeCue.id === selectedId) return;
    selectCueId(activeCue.id);
  }, [activeCue, dirty, follow, selectCueId, selectedId]);

  useEffect(() => {
    const finishArrowHold = (event: KeyboardEvent) => {
      const hold = arrowHoldRef.current;
      if (!hold || event.key !== hold.key) return;
      window.clearTimeout(hold.timer);
      if (hold.interval != null) window.clearInterval(hold.interval);
      const media = mediaRef.current;
      if (!hold.long && media) {
        const direction = hold.key === "ArrowRight" ? 1 : -1;
        seek(Math.max(0, Math.min(media.duration || session?.media.duration || 0, media.currentTime + direction * 5)));
        showPlaybackNotice(direction > 0 ? "+5s" : "−5s");
      } else if (hold.key === "ArrowRight" && media) {
        media.playbackRate = hold.previousRate;
        setPlaybackRate(hold.previousRate);
        setPlaybackNotice(null);
      } else if (hold.long) {
        setPlaybackNotice(null);
      }
      arrowHoldRef.current = null;
    };

    const handler = (event: KeyboardEvent) => {
      if (isInteractiveTarget(event.target)) return;
      if (event.code === "Space") {
        event.preventDefault();
        togglePlayback();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        if (event.repeat) return;
        if (arrowHoldRef.current || !mediaRef.current) return;
        const key = event.key as ArrowHold["key"];
        const previousRate = mediaRef.current.playbackRate;
        const hold: ArrowHold = {
          key,
          timer: 0,
          interval: null,
          long: false,
          previousRate,
        };
        hold.timer = window.setTimeout(() => {
          const media = mediaRef.current;
          if (!media || arrowHoldRef.current !== hold) return;
          hold.long = true;
          if (key === "ArrowRight") {
            media.playbackRate = 2;
            setPlaybackRate(2);
            setPlaybackNotice("2×");
            void media.play();
          } else {
            setPlaybackNotice("−2×");
            hold.interval = window.setInterval(() => {
              const current = mediaRef.current;
              if (current) seek(Math.max(0, current.currentTime - 0.2));
            }, 100);
          }
        }, 350);
        arrowHoldRef.current = hold;
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        changeVolume((mediaRef.current?.volume ?? 1) + 0.05);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        changeVolume((mediaRef.current?.volume ?? 1) - 0.05);
      } else if (event.key.toLowerCase() === "m") {
        event.preventDefault();
        toggleMute();
      } else if (event.key.toLowerCase() === "f" && !event.shiftKey) {
        event.preventDefault();
        toggleFullscreen();
      }
    };
    window.addEventListener("keydown", handler);
    window.addEventListener("keyup", finishArrowHold);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("keyup", finishArrowHold);
      const hold = arrowHoldRef.current;
      if (hold) {
        window.clearTimeout(hold.timer);
        if (hold.interval != null) window.clearInterval(hold.interval);
        if (hold.long && hold.key === "ArrowRight" && mediaRef.current) {
          mediaRef.current.playbackRate = hold.previousRate;
        }
        arrowHoldRef.current = null;
      }
    };
  }, [changeVolume, seek, session?.media.duration, showPlaybackNotice, toggleFullscreen, toggleMute, togglePlayback]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isInteractiveTarget(event.target)) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        void (event.shiftKey ? redo() : undo());
        return;
      }
      if (event.key === "Enter" && event.shiftKey) {
        event.preventDefault();
        void saveAndNext();
      } else if (event.key === "Enter") {
        event.preventDefault();
        void mark("reviewed");
      } else if (event.key.toLowerCase() === "f" && event.shiftKey) {
        event.preventDefault();
        void mark("flagged");
      } else if (event.key.toLowerCase() === "s") {
        void splitCurrent();
      } else if (event.key === "[" || event.key === "]") {
        updateDraft(
          event.key === "["
            ? { start: currentTimeRef.current }
            : { end: currentTimeRef.current },
        );
      } else if (event.key.toLowerCase() === "j") {
        seek(Math.max(0, currentTimeRef.current - 2));
        if (mediaRef.current) mediaRef.current.playbackRate = 0.75;
        void mediaRef.current?.play();
      } else if (event.key.toLowerCase() === "k") {
        mediaRef.current?.pause();
      } else if (event.key.toLowerCase() === "l") {
        if (mediaRef.current) mediaRef.current.playbackRate = 1.5;
        void mediaRef.current?.play();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [mark, redo, saveAndNext, seek, splitCurrent, undo, updateDraft]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return cues.filter((cue) => {
      const matchesFilter =
        filter === "all" ||
        (filter === "missing" && !cue.target?.trim()) ||
        (filter === "over_budget" && cue.over_budget) ||
        (filter === "time_warning" && cue.time_warning) ||
        (filter === "term_warning" && cue.term_warning) ||
        cue.status === filter;
      const matchesSearch =
        !query ||
        String(cue.id) === query.replace(/^#/, "") ||
        cue.source.toLocaleLowerCase().includes(query) ||
        cue.target?.toLocaleLowerCase().includes(query);
      return matchesFilter && Boolean(matchesSearch);
    });
  }, [cues, filter, search]);

  if (!session) {
    return (
      <div className="loading-screen">
        <LoaderCircle className="loading-spinner" />
        <h1>OpenBBQ Review</h1>
        <p>{message ?? t("app.loading")}</p>
      </div>
    );
  }

  const overlayCue = activeCue ?? selectedCue;
  const saveText = {
    saved: t("app.saved"),
    saving: t("app.saving"),
    failed: t("app.saveFailed"),
    conflict: t("app.conflict"),
  }[saveState];
  const primaryFilters: Array<[Filter, string, number]> = [
    ["unreviewed", t("filter.unreviewed"), session.progress.unreviewed],
    ["reviewed", t("filter.reviewed"), session.progress.reviewed],
    ["flagged", t("filter.flagged"), session.progress.flagged],
    ["all", t("filter.all"), session.progress.total],
  ];
  const qualityFilters: Array<[Filter, string]> = [
    ["missing", t("filter.missing")],
    ["over_budget", t("filter.overBudget")],
    ["time_warning", t("filter.timeWarning")],
    ["term_warning", t("filter.termWarning")],
  ];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-copy">
            <strong>OpenBBQ Review</strong>
            <span className="brand-subtitle" title={session.workspace}>{session.title}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <IconButton
            label={locale === "en" ? t("app.localeChinese") : t("app.localeEnglish")}
            onClick={() => setLocale(locale === "en" ? "zh" : "en")}
          >
            <Languages />
          </IconButton>
          <IconButton
            label={resolvedTheme === "dark" ? t("app.themeLight") : t("app.themeDark")}
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          >
            {resolvedTheme === "dark" ? <Sun /> : <Moon />}
          </IconButton>
          <div className={`save-indicator ${saveState}`} role="status">
            {saveState === "saving" ? <LoaderCircle /> : saveState === "saved" ? <CheckCircle2 /> : <CircleAlert />}
            <span>{saveText}</span>
          </div>
          <div className="progress-summary">
            <strong>{t("app.progress", { reviewed: session.progress.reviewed, total: session.progress.total })}</strong>
            {session.progress.flagged > 0 && <span>{t("app.flaggedProgress", { count: session.progress.flagged })}</span>}
          </div>
        </div>
      </header>

      {message && (
        <div className={`message-banner ${saveState === "conflict" ? "danger" : ""}`}>
          <span>{message}</span>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RotateCcw /> {t("app.reloadDiscard")}
          </Button>
        </div>
      )}

      <main className="workspace-grid">
        <section className="preview-column" aria-label={t("app.mediaTimeline")}>
          <div className="media-panel" ref={mediaPanelRef}>
            {session.media.kind === "video" && session.media.playable ? (
              <video
                ref={attachMedia}
                src={session.media.url}
                preload="metadata"
                tabIndex={0}
                aria-label={session.media.name}
                onClick={togglePlayback}
                onError={() => void startBrowserPreview()}
                onTimeUpdate={(event) => handleMediaTime(event.currentTarget)}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onRateChange={(event) => setPlaybackRate(event.currentTarget.playbackRate)}
                onVolumeChange={(event) => {
                  setVolume(event.currentTarget.volume);
                  setMuted(event.currentTarget.muted);
                }}
              />
            ) : session.media.kind === "audio" && session.media.playable ? (
              <div className="audio-stage">
                <AudioWaveform className="audio-icon" aria-hidden="true" />
                <strong>{t("app.audio")}</strong>
                <audio
                  ref={attachMedia}
                  src={session.media.url}
                  preload="metadata"
                  onTimeUpdate={(event) => handleMediaTime(event.currentTarget)}
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  onRateChange={(event) => setPlaybackRate(event.currentTarget.playbackRate)}
                  onVolumeChange={(event) => {
                    setVolume(event.currentTarget.volume);
                    setMuted(event.currentTarget.muted);
                  }}
                />
              </div>
            ) : (
              <div className="proxy-stage">
                <LoaderCircle className="loading-spinner" />
                <strong>{t("app.proxyTitle")}</strong>
                <p>{t("app.proxyDescription")}</p>
                <span>{session.media.preview_status === "building" ? t("app.transcoding") : session.media.preview_status}</span>
                {session.media.preview_error && <code>{session.media.preview_error}</code>}
                {session.media.preview_status === "failed" && (
                  <Button
                    variant="outline"
                    onClick={() => void startBrowserPreview()}
                  >
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
            {playbackNotice && (
              <div className="playback-notice" role="status" aria-live="polite">
                {playbackNotice}
              </div>
            )}
            {session.media.playable && (
              <div className="player-controls" role="group" aria-label={t("transport.controls")}>
                <Slider
                  className="player-progress"
                  min={0}
                  max={session.media.duration}
                  step={0.01}
                  value={[Math.min(currentTime, session.media.duration)]}
                  onValueChange={(value) => seek(Array.isArray(value) ? (value[0] ?? 0) : value)}
                  aria-label={t("transport.progress")}
                />
                <div className="player-control-row">
                  <div className="player-control-cluster">
                    <IconButton
                      className="play-button"
                      label={isPlaying ? t("transport.pause") : t("transport.play")}
                      shortcut="Space"
                      onClick={togglePlayback}
                    >
                      {isPlaying ? <Pause /> : <Play />}
                    </IconButton>
                    <IconButton label={t("transport.skipBack")} shortcut="←" onClick={() => seek(Math.max(0, currentTime - 5))}>
                      <SkipBack />
                    </IconButton>
                    <IconButton
                      label={t("transport.skipForward")}
                      shortcut="→"
                      onClick={() => seek(Math.min(session.media.duration, currentTime + 5))}
                    >
                      <SkipForward />
                    </IconButton>
                    <span className="timecode">{formatPlayerTime(currentTime)} <span>/ {formatPlayerTime(session.media.duration)}</span></span>
                  </div>
                  <div className="player-control-cluster player-control-cluster-end">
                    <div className="volume-control">
                      <Button
                        className="volume-button"
                        size="icon"
                        variant="ghost"
                        aria-label={muted ? t("transport.unmute") : t("transport.mute")}
                        onClick={toggleMute}
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
                            changeVolume((muted ? 0 : volume) + (event.key === "ArrowUp" ? 0.05 : -0.05));
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
                              changePlaybackRate(rate);
                              event.currentTarget.blur();
                            }}
                          >
                            {rate}×
                          </button>
                        ))}
                      </div>
                    </div>
                    <Select value={overlay} onValueChange={(value) => value && setOverlay(value as Overlay)}>
                      <SelectTrigger className="player-select subtitle-select" size="sm" aria-label={t("transport.subtitles")}>
                        <Captions /><SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="bilingual">{t("overlay.bilingual")}</SelectItem>
                        <SelectItem value="target">{t("overlay.target")}</SelectItem>
                        <SelectItem value="source">{t("overlay.source")}</SelectItem>
                        <SelectItem value="hidden">{t("overlay.hidden")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <IconButton label={t("transport.fullscreen")} shortcut="F" onClick={toggleFullscreen}>
                      <Maximize />
                    </IconButton>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="control-deck">
            <div className="edit-toolbar">
              <IconButton label={t("action.undo")} shortcut="⌘Z" onClick={() => void undo()}><Undo2 /></IconButton>
              <IconButton label={t("action.redo")} shortcut="⇧⌘Z" onClick={() => void redo()}><Redo2 /></IconButton>
              <span className="toolbar-separator" />
              <IconButton label={t("action.insert")} onClick={() => void insertAtPlayhead()}><Plus /></IconButton>
              <IconButton label={t("action.split")} shortcut="S" onClick={() => void splitCurrent()}><Scissors /></IconButton>
              <IconButton label={t("action.merge")} onClick={() => void mergeNext()}><Combine /></IconButton>
              <IconButton label={t("action.delete")} variant="destructive" onClick={() => setDeleteOpen(true)}><Trash2 /></IconButton>
            </div>

            <div className="timeline-toolbar">
              <div className="timeline-heading">
                <strong>{t("timeline.title")}</strong>
                <span>{t("timeline.hint")}</span>
              </div>
              <div className="snap-control" title={snapEnabled ? t("timeline.snapOn") : t("timeline.snapOff")}>
                <Magnet />
                <Switch
                  size="sm"
                  checked={snapEnabled}
                  aria-label={snapEnabled ? t("timeline.snapOn") : t("timeline.snapOff")}
                  onCheckedChange={setSnapEnabled}
                />
              </div>
              <IconButton
                label={t("transport.loop")}
                variant={loopCue ? "secondary" : "ghost"}
                onClick={() => setLoopCue((value) => !value)}
              >
                <Repeat2 />
              </IconButton>
              <IconButton
                label={t("timeline.zoomOut")}
                disabled={zoom <= 1}
                onClick={() => setZoom((value) => Math.max(1, value - (value <= 8 ? 0.5 : value <= 24 ? 2 : 8)))}
              >
                <ZoomOut />
              </IconButton>
              <Slider
                className="zoom-slider"
                min={1}
                max={MAX_TIMELINE_ZOOM}
                step={0.5}
                value={[zoom]}
                onValueChange={(value) => setZoom(Array.isArray(value) ? (value[0] ?? 1) : value)}
                aria-label={t("timeline.title")}
              />
              <span className="zoom-value">{zoom.toFixed(1)}×</span>
              <IconButton
                label={t("timeline.zoomIn")}
                disabled={zoom >= MAX_TIMELINE_ZOOM}
                onClick={() => setZoom((value) => Math.min(MAX_TIMELINE_ZOOM, value + (value < 8 ? 0.5 : value < 24 ? 2 : 8)))}
              >
                <ZoomIn />
              </IconButton>
              <IconButton
                label={t("timeline.fitCue")}
                disabled={!draft}
                onClick={() => {
                  if (!draft) return;
                  setZoom(fitCueZoom(session.media.duration, { start: draft.start, end: draft.end }));
                  seek((draft.start + draft.end) / 2);
                }}
              >
                <Focus />
              </IconButton>
              <IconButton label={largeTimeline ? t("timeline.collapse") : t("timeline.expand")} onClick={() => setLargeTimeline((value) => !value)}>
                {largeTimeline ? <Minimize2 /> : <Maximize2 />}
              </IconButton>
            </div>

            <Timeline
              cues={cues}
              currentTime={currentTime}
              duration={session.media.duration}
              selectedId={selectedId}
              zoom={zoom}
              large={largeTimeline}
              snapEnabled={snapEnabled}
              theme={resolvedTheme}
              ariaLabel={t("timeline.aria")}
              isPlaying={isPlaying}
              getPlaybackTime={getPlaybackTime}
              onSeek={seek}
              onSelect={(id) => {
                const cue = cues.find((item) => item.id === id);
                if (cue) void selectCue(cue);
              }}
              onTimeChange={updateTimeline}
            />

            {draft && selectedCue && (
              <div className="precision-strip">
                <div className="precision-cue" aria-label={`${t("timeline.selectedCue")} #${selectedCue.id}`} title={t("timeline.selectedCue")}>
                  <strong>#{selectedCue.id}</strong>
                </div>
                <TimeNudge
                  label={t("timeline.start")}
                  compactLabel="IN"
                  value={draft.start}
                  earlierLabel={t("timeline.nudgeStartEarlier")}
                  laterLabel={t("timeline.nudgeStartLater")}
                  onEarlier={() => nudgeSelected("start", -1)}
                  onLater={() => nudgeSelected("start", 1)}
                />
                <TimeNudge
                  label={t("timeline.end")}
                  compactLabel="OUT"
                  value={draft.end}
                  earlierLabel={t("timeline.nudgeEndEarlier")}
                  laterLabel={t("timeline.nudgeEndLater")}
                  onEarlier={() => nudgeSelected("end", -1)}
                  onLater={() => nudgeSelected("end", 1)}
                />
                <div className="precision-duration" aria-label={`${t("timeline.duration")} ${formatDuration(draft.end - draft.start)}`} title={t("timeline.duration")}>
                  <strong>{formatDuration(draft.end - draft.start)}</strong>
                </div>
                <Select value={String(nudgeStep)} onValueChange={(value) => value && setNudgeStep(Number(value))}>
                  <SelectTrigger className="nudge-step-select" size="sm" aria-label={t("timeline.step")}>
                    <SelectValue>{Math.round(nudgeStep * 1000)}ms</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {[0.01, 0.05, 0.1, 0.5].map((step) => <SelectItem key={step} value={String(step)}>{Math.round(step * 1000)} ms</SelectItem>)}
                  </SelectContent>
                </Select>
                <div className="body-nudge">
                  <IconButton size="icon-xs" label={t("timeline.nudgeEarlier")} onClick={() => nudgeSelected("body", -1)}><SkipBack /></IconButton>
                  <IconButton size="icon-xs" label={t("timeline.nudgeLater")} onClick={() => nudgeSelected("body", 1)}><SkipForward /></IconButton>
                </div>
              </div>
            )}
          </div>
        </section>

        <aside className="cue-column" aria-label={t("app.cueList")}>
          <div className="cue-toolbar">
            <div className="filter-row">
              {primaryFilters.map(([value, label, count]) => (
                <Button
                  className="status-filter"
                  key={value}
                  size="sm"
                  variant="ghost"
                  aria-label={`${label} ${count}`}
                  aria-pressed={filter === value}
                  title={label}
                  onClick={() => setFilter(value)}
                >
                  <span>{label}</span>
                  <span className="filter-count">{count}</span>
                </Button>
              ))}
              <DropdownMenu>
                <DropdownMenuTrigger render={<Button size="icon-sm" variant={qualityFilters.some(([value]) => value === filter) ? "secondary" : "ghost"} aria-label={t("action.moreFilters")} title={t("action.moreFilters")} />}>
                  <Filter />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuRadioGroup value={filter} onValueChange={(value) => setFilter(value as Filter)}>
                    {qualityFilters.map(([value, label]) => <DropdownMenuRadioItem key={value} value={value}>{label}</DropdownMenuRadioItem>)}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="search-row">
              <Search aria-hidden="true" />
              <Input
                type="search"
                aria-label={t("filter.search")}
                placeholder={t("filter.search")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <Button
                className="follow-button"
                size="sm"
                variant={follow ? "secondary" : "outline"}
                aria-pressed={follow}
                onClick={() => {
                  if (follow) {
                    setFollow(false);
                    return;
                  }
                  setFollow(true);
                  if (activeCue) selectCueId(activeCue.id);
                }}
              >
                <LocateFixed />
                <span>{follow ? t("filter.following") : t("action.backToPlayback")}</span>
              </Button>
            </div>
          </div>

          <div className="cue-table-head" aria-hidden="true">
            <span>#</span><span>IN / OUT</span><span>{t("timeline.duration")}</span><span>{t("cue.source")}</span><span />
          </div>
          <div className="cue-list" onWheel={() => setFollow(false)}>
            {filtered.length === 0 && <div className="empty-state">{t("filter.empty")}</div>}
            {filtered.map((cue) => {
              const selected = cue.id === selectedId;
              return (
                <article
                  key={cue.id}
                  ref={selected ? selectedCardRef : undefined}
                  className={`cue-row ${selected ? "selected" : ""} status-${cue.status}`}
                >
                  <button className="cue-summary" onClick={() => void selectCue(cue)}>
                    <StatusIcon status={cue.status} />
                    <strong>{cue.id}</strong>
                    <span className="cue-time"><b>{shortTime(cue.start)}</b><b>{shortTime(cue.end)}</b></span>
                    <span className="cue-duration">{formatDuration(cue.duration)}</span>
                    <span className="cue-preview">
                      <b>{cue.source || t("cue.blank")}</b>
                      {cue.target && <span>{cue.target}</span>}
                    </span>
                    <span className="cue-warnings">
                      {cue.over_budget && <Badge variant="outline" title={t("warning.overBudgetHint")}>{t("warning.overBudget")}</Badge>}
                      {cue.time_warning && <Badge variant="outline" title={t("warning.timeHint")}>{t("warning.time")}</Badge>}
                      {cue.term_warning && <Badge variant="outline" title={t("warning.termHint")}>{t("warning.term")}</Badge>}
                    </span>
                  </button>
                </article>
              );
            })}
          </div>

          {selectedCue && draft && (
            <section className="cue-editor" aria-label={`${t("timeline.selectedCue")} #${selectedCue.id}`}>
              <div className="editor-header">
                <div>
                  <StatusIcon status={selectedCue.status} />
                  <strong>#{selectedCue.id}</strong>
                  <span>{t(`cue.status.${selectedCue.status}`)}</span>
                </div>
                <div className="metric-row">
                  <span>{formatDuration(draft.end - draft.start)}</span>
                  <span>{t("cue.sourceCps", { value: selectedCue.source_cps })}</span>
                  {selectedCue.budget && <span>{t("cue.budget", { used: draft.target.length, limit: selectedCue.budget.max_chars })}</span>}
                  <IconButton
                    size="icon-xs"
                    label={t("cue.note")}
                    variant={showNote || draft.note ? "secondary" : "ghost"}
                    onClick={() => setShowNote((value) => !value)}
                  >
                    <MessageSquareText />
                  </IconButton>
                </div>
              </div>
              <label className="editor-field">
                <span>{t("cue.source")}</span>
                <Textarea
                  ref={sourceRef}
                  value={draft.source}
                  rows={2}
                  onChange={(event) => updateDraft({ source: event.target.value })}
                />
              </label>
              <div className="editor-field translation-field">
                <div className="translation-field-header">
                  <label htmlFor={`target-${selectedCue.id}`}>{t("cue.translationField")}</label>
                  <Select
                    value={session.target_lang ?? "source"}
                    onValueChange={(value) => value && void switchLanguage(String(value))}
                  >
                    <SelectTrigger className="editor-language-select" size="sm" aria-label={t("app.reviewLanguage")}>
                      <Captions aria-hidden="true" />
                      <SelectValue>
                        {session.target_lang ? languageName(session.target_lang, locale) : t("app.sourceOnly")}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="source">{t("app.sourceOnly")}</SelectItem>
                      {session.languages.map((language) => (
                        <SelectItem key={language} value={language}>{languageName(language, locale)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {session.target_lang ? (
                  <Textarea
                    id={`target-${selectedCue.id}`}
                    ref={targetRef}
                    value={draft.target}
                    rows={2}
                    aria-label={t("cue.translation", { language: session.target_lang })}
                    onChange={(event) => updateDraft({ target: event.target.value })}
                  />
                ) : (
                  <p className="source-only-hint">{t("cue.sourceOnlyHint")}</p>
                )}
              </div>
              <div className="time-inputs">
                <label>
                  <span>{t("timeline.start")}</span>
                  <Input type="number" min="0" step="0.001" value={draft.start} onChange={(event) => {
                    updateDraft({ start: Number(event.target.value) });
                  }} />
                </label>
                <label>
                  <span>{t("timeline.end")}</span>
                  <Input type="number" min="0" step="0.001" value={draft.end} onChange={(event) => {
                    updateDraft({ end: Number(event.target.value) });
                  }} />
                </label>
              </div>
              {selectedCue.over_budget && <div className="validation-warning"><CircleAlert />{t("cue.overBudget")}</div>}
              {showNote && (
                <label className="editor-field note-field">
                  <span>{t("cue.note")}</span>
                  <Input type="text" value={draft.note} placeholder={t("cue.notePlaceholder")} onChange={(event) => {
                    updateDraft({ note: event.target.value });
                  }} />
                </label>
              )}
              <div className="review-actions">
                <Button onClick={() => void mark("reviewed")}><Check />{t("action.review")}<kbd>Enter</kbd></Button>
                <Button variant="outline" onClick={() => void mark("flagged")}><Flag />{t("action.flag")}<kbd>F</kbd></Button>
              </div>
            </section>
          )}
        </aside>
      </main>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("action.delete")}</AlertDialogTitle>
            <AlertDialogDescription>{t("error.deleteConfirm", { id: selectedCue?.id ?? "" })}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>{locale === "zh" ? "取消" : "Cancel"}</Button>
            <Button variant="destructive" onClick={() => {
              setDeleteOpen(false);
              void deleteCurrent();
            }}>{t("action.delete")}</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );

  function handleError(error: unknown) {
    if (error instanceof ApiError) {
      if (error.status === 409) {
        setSaveState("conflict");
        setMessage(t("error.conflict"));
      } else {
        setSaveState("failed");
        const detail = error.payload.detail ? `: ${String(error.payload.detail)}` : "";
        setMessage(`${String(error.payload.error ?? error.message)}${detail}`);
      }
    } else {
      setSaveState("failed");
      setMessage(error instanceof Error ? error.message : t("error.unknown"));
    }
  }
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
  compactLabel: "IN" | "OUT";
  value: number;
  earlierLabel: string;
  laterLabel: string;
  onEarlier: () => void;
  onLater: () => void;
}) {
  return (
    <div className="time-nudge" role="group" aria-label={label} title={label}>
      <span aria-hidden="true">{compactLabel}</span>
      <IconButton size="icon-xs" label={earlierLabel} onClick={onEarlier}><SkipBack /></IconButton>
      <strong>{formatPrecisionTime(value)}</strong>
      <IconButton size="icon-xs" label={laterLabel} onClick={onLater}><SkipForward /></IconButton>
    </div>
  );
}

function StatusIcon({ status }: { status: ReviewStatus }) {
  if (status === "reviewed") return <CheckCircle2 className="status-icon reviewed" aria-hidden="true" />;
  if (status === "flagged") return <Flag className="status-icon flagged" aria-hidden="true" />;
  return <Circle className="status-icon unreviewed" aria-hidden="true" />;
}

function formatPrecisionTime(seconds: number) {
  const safeSeconds = Math.max(0, seconds);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const rest = safeSeconds % 60;
  const minuteTime = `${String(minutes).padStart(2, "0")}:${rest.toFixed(3).padStart(6, "0")}`;
  return hours > 0 ? `${String(hours).padStart(2, "0")}:${minuteTime}` : minuteTime;
}

function languageName(language: string, locale: "en" | "zh") {
  try {
    return new Intl.DisplayNames([locale], { type: "language" }).of(language) ?? language;
  } catch {
    return language;
  }
}

function formatPlayerTime(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function shortTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds % 60).toFixed(3).padStart(6, "0");
  return `${String(minutes).padStart(2, "0")}:${rest}`;
}

function formatDuration(seconds: number) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}
