import { ApiError, authenticateFromFragment, opId, type Api } from "../api/client";
import type {
  BatchDryRunResult,
  Cue,
  IssueKind,
  ReviewStatus,
  Snapshot,
  Suggestion,
} from "../api/types";
import type { MessageKey } from "../app/i18n";
import type { PlayerController } from "../player/controller";
import { snapSplitPoint, sourceIndexForSnap } from "./split-snap";
import { fitCueZoom, nudgeCueRange, cueMovementBounds, type NudgeTarget } from "../timeline/timeline-model";
import { updatePrefs } from "../store/prefs";
import { draftEquals, findCue } from "../store/selectors";
import type { AppStore, Draft } from "../store/state";

export type Localizer = (key: MessageKey, values?: Record<string, string | number>) => string;

const fallbackLocalizer: Localizer = (key) => key;

export interface BatchReplaceParams {
  find: string;
  replace: string;
  fields: Array<"source" | "target">;
  caseSensitive: boolean;
  regex: boolean;
  cueIds?: number[];
}

export interface CommandCenterOptions {
  store: AppStore;
  api: Api;
  player: PlayerController;
  /** When the user already stored a zoom preference, initial load keeps it. */
  hadStoredZoom?: boolean;
}

/**
 * Every data-changing intent funnels through this layer: UI event → command →
 * guards (no-change detection, draft validation) → API with base_revision +
 * op_id → snapshot applied to the store. A guard failure means NO request, so
 * no-op mutations (the old click-to-PATCH bug) cannot happen here.
 */
export class CommandCenter {
  readonly editorRefs: { source: HTMLTextAreaElement | null; target: HTMLTextAreaElement | null } = {
    source: null,
    target: null,
  };

  private store: AppStore;
  private api: Api;
  private player: PlayerController;
  private hadStoredZoom: boolean;
  private t: Localizer = fallbackLocalizer;
  private savePromise: Promise<string> | null = null;
  private autosaveTimer: number | null = null;
  private toastTimer: number | null = null;

  constructor(options: CommandCenterOptions) {
    this.store = options.store;
    this.api = options.api;
    this.player = options.player;
    this.hadStoredZoom = options.hadStoredZoom ?? false;
  }

  setLocalizer(localizer: Localizer): void {
    this.t = localizer;
  }

  dispose(): void {
    if (this.autosaveTimer != null) window.clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    if (this.toastTimer != null) window.clearTimeout(this.toastTimer);
    this.toastTimer = null;
  }

  showToast(text: string, duration = 3000): void {
    if (this.toastTimer != null) window.clearTimeout(this.toastTimer);
    this.store.setState({ toast: text });
    this.toastTimer = window.setTimeout(() => {
      this.toastTimer = null;
      this.store.setState({ toast: null });
    }, duration);
  }

  // ---------------------------------------------------------------- session

  async load(): Promise<void> {
    try {
      await authenticateFromFragment();
      const [session, snapshot] = await Promise.all([this.api.session(), this.api.cues()]);
      const initial =
        snapshot.cues.find((cue) => cue.status === "unreviewed") ?? snapshot.cues[0] ?? null;
      this.store.setState({
        session,
        cues: snapshot.cues,
        revision: snapshot.revision,
        progress: snapshot.progress,
        suggestions: snapshot.suggestions,
        selectedId: initial?.id ?? null,
        selection: initial ? [initial.id] : [],
        currentTime: initial?.start ?? 0,
        draft: null,
        dirty: false,
        saveState: "saved",
        banner: null,
        showNote: false,
      });
      if (initial && !this.hadStoredZoom) {
        const zoom = fitCueZoom(session.media.duration, initial);
        updatePrefs(this.store, { zoom });
      }
    } catch (error) {
      this.handleError(error);
    }
  }

  /** Conflict recovery: drop the local draft and reload the latest snapshot. */
  async reloadDiscard(): Promise<void> {
    this.store.setState({ dirty: false, draft: null });
    await this.load();
  }

  // ------------------------------------------------------------ draft edits

  updateDraft(changes: Partial<Draft>): void {
    const state = this.store.getState();
    if (!state.draft) return;
    const next = { ...state.draft, ...changes };
    if (draftEquals(next, state.draft)) return;
    this.store.setState({
      draft: next,
      dirty: true,
      saveState: state.saveState === "failed" ? "saving" : state.saveState,
    });
    this.scheduleAutosave();
  }

  private scheduleAutosave(): void {
    if (this.store.getState().saveState === "conflict") return;
    if (this.autosaveTimer != null) window.clearTimeout(this.autosaveTimer);
    this.autosaveTimer = window.setTimeout(() => {
      this.autosaveTimer = null;
      void this.persistDraft().catch(() => undefined);
    }, 400);
  }

  /**
   * Serialized autosave: one in-flight save at a time, and the loop drains
   * edits that arrived while a request was outstanding. Draft-vs-snapshot
   * diffing skips no-change saves entirely (zero requests).
   */
  async persistDraft(): Promise<string> {
    if (this.savePromise) return this.savePromise;
    const promise = (async () => {
      while (this.store.getState().dirty) {
        const state = this.store.getState();
        if (state.saveState === "conflict") return state.revision;
        const draftSnapshot = state.draft;
        const cueId = state.selectedId;
        if (!draftSnapshot || cueId == null) return state.revision;
        const cueSnapshot = findCue(state.cues, cueId);
        const contentChanged =
          cueSnapshot == null ||
          draftSnapshot.source !== cueSnapshot.source ||
          draftSnapshot.target !== (cueSnapshot.target ?? "") ||
          draftSnapshot.start !== cueSnapshot.start ||
          draftSnapshot.end !== cueSnapshot.end;
        const noteChanged = draftSnapshot.note !== (cueSnapshot?.note ?? "");
        if (!contentChanged && !noteChanged) {
          this.store.setState({ dirty: false, saveState: "saved" });
          return state.revision;
        }
        if (!(draftSnapshot.start < draftSnapshot.end)) {
          // Client-side start<end validation blocks the command, not the server.
          this.store.setState({
            saveState: "failed",
            banner: { danger: false, text: this.t("cue.timeOrder") },
          });
          return state.revision;
        }
        this.store.setState({ saveState: "saving" });
        let response = contentChanged
          ? await this.api.updateCue(cueId, {
              base_revision: this.store.getState().revision,
              op_id: opId("edit"),
              source: draftSnapshot.source,
              ...(state.session?.target_lang ? { target: draftSnapshot.target } : {}),
              start: Number(draftSnapshot.start.toFixed(3)),
              end: Number(draftSnapshot.end.toFixed(3)),
            })
          : await this.api.setStatus(cueId, {
              base_revision: this.store.getState().revision,
              op_id: opId("note"),
              status: cueSnapshot?.status ?? "unreviewed",
              note: draftSnapshot.note || null,
            });
        if (contentChanged && noteChanged) {
          // Preserve the current status; note saves never reset it.
          response = await this.api.setStatus(cueId, {
            base_revision: response.revision,
            op_id: opId("note"),
            status: cueSnapshot?.status ?? "unreviewed",
            note: draftSnapshot.note || null,
          });
        }
        const hasNewerDraft =
          this.store.getState().draft !== draftSnapshot ||
          this.store.getState().selectedId !== cueId;
        this.applyResponse(response, !hasNewerDraft);
        if (!hasNewerDraft) return response.revision;
      }
      return this.store.getState().revision;
    })()
      .catch((error) => {
        this.handleError(error);
        throw error;
      })
      .finally(() => {
        this.savePromise = null;
      });
    this.savePromise = promise;
    return promise;
  }

  applyResponse(response: Snapshot, markClean = !this.store.getState().dirty): void {
    this.store.setState((state) => ({
      revision: response.revision,
      cues: response.cues,
      suggestions: response.suggestions,
      progress: response.progress,
      session: state.session ? { ...state.session, progress: response.progress } : state.session,
      ...(markClean
        ? { dirty: false, saveState: "saved" as const }
        : { saveState: "saving" as const }),
      banner: null,
    }));
  }

  private async runMutation(
    operation: (baseRevision: string) => Promise<Snapshot>,
  ): Promise<Snapshot | null> {
    try {
      const base = await this.persistDraft();
      this.store.setState({ saveState: "saving" });
      const response = await operation(base);
      this.applyResponse(response);
      return response;
    } catch (error) {
      this.handleError(error);
      return null;
    }
  }

  handleError(error: unknown): void {
    if (error instanceof ApiError) {
      if (error.status === 409) {
        this.store.setState({
          saveState: "conflict",
          banner: { danger: true, text: this.t("error.conflict") },
        });
      } else {
        const detail = error.payload.detail ? `: ${String(error.payload.detail)}` : "";
        this.store.setState({
          saveState: "failed",
          banner: {
            danger: false,
            text: `${String(error.payload.error ?? error.message)}${detail}`,
          },
        });
      }
    } else {
      this.store.setState({
        saveState: "failed",
        banner: {
          danger: false,
          text: error instanceof Error ? error.message : this.t("error.unknown"),
        },
      });
    }
  }

  // ------------------------------------------------------------- selection

  async selectCue(cue: Cue): Promise<void> {
    try {
      await this.persistDraft();
      this.store.setState({ selectedId: cue.id, selection: [cue.id], dirty: false });
      this.player.seek(cue.start);
      // Explicit navigation interrupts a watch-through: pause, or follow
      // would yank the selection away at the next cue boundary.
      if (this.store.getState().isPlaying) this.player.pause();
    } catch {
      // The conflict banner preserves the unsaved draft.
    }
  }

  async selectCueById(id: number): Promise<void> {
    const cue = findCue(this.store.getState().cues, id);
    if (cue) await this.selectCue(cue);
  }

  setSelected(id: number | null): void {
    if (!this.store.getState().dirty) this.store.setState({ selectedId: id });
  }

  // ------------------------------------------------------------ cue actions

  async mark(status: ReviewStatus): Promise<void> {
    const state = this.store.getState();
    if (state.selectedId == null) return;
    const cueId = state.selectedId;
    const response = await this.runMutation((base) =>
      this.api.setStatus(cueId, {
        base_revision: base,
        op_id: opId(`status-${status}`),
        status,
        note: state.draft?.note || null,
      }),
    );
    if (response && status === "reviewed") {
      const index = response.cues.findIndex((cue) => cue.id === cueId);
      const next = nextUnreviewed(response.cues, index);
      if (next) {
        this.store.setState({ selectedId: next.id, selection: [next.id] });
        this.player.seek(next.start);
      }
    }
  }

  async saveAndNext(): Promise<void> {
    const state = this.store.getState();
    if (state.selectedId == null) return;
    try {
      await this.persistDraft();
      const { cues, selectedId } = this.store.getState();
      const index = cues.findIndex((cue) => cue.id === selectedId);
      const next = nextUnreviewed(cues, index);
      if (next) {
        this.store.setState({ selectedId: next.id, selection: [next.id] });
        this.player.seek(next.start);
      }
    } catch {
      // The visible save banner keeps the current draft recoverable.
    }
  }

  /** Timeline drag result. No-change guard: identical range → zero requests. */
  async setCueTime(cueId: number, start: number, end: number): Promise<void> {
    const cue = findCue(this.store.getState().cues, cueId);
    if (!cue || (cue.start === start && cue.end === end)) return;
    await this.runMutation((base) =>
      this.api.updateCue(cueId, { base_revision: base, op_id: opId("timeline"), start, end }),
    );
  }

  nudgeSelected(target: NudgeTarget, direction: -1 | 1): void {
    const state = this.store.getState();
    if (!state.draft || !state.session) return;
    const index = state.cues.findIndex((cue) => cue.id === state.selectedId);
    const next = nudgeCueRange(
      { start: state.draft.start, end: state.draft.end },
      target,
      state.prefs.nudgeStep * direction,
      state.session.media.duration,
      cueMovementBounds(state.cues, index, state.session.media.duration),
    );
    this.updateDraft(next);
  }

  async splitCurrent(): Promise<void> {
    const state = this.store.getState();
    const selected = findCue(state.cues, state.selectedId);
    const draft = state.draft;
    const playhead = this.player.getPlaybackTime();
    if (!selected || !draft || playhead <= selected.start || playhead >= selected.end) {
      this.store.setState({ banner: { danger: false, text: this.t("error.split") } });
      return;
    }
    // §7: snap the default cut point to a nearby word boundary when the
    // timeline's word data covers the playhead.
    const snap = snapSplitPoint(
      playhead,
      state.transcriptWords,
      selected.start,
      selected.end,
    );
    const at = snap?.time ?? playhead;
    const ratio = (at - selected.start) / selected.duration;
    let sourceIndex: number | null = null;
    if (snap) {
      sourceIndex = sourceIndexForSnap(draft.source, snap, ratio);
    }
    sourceIndex ??=
      this.editorRefs.source?.selectionStart ?? Math.round(draft.source.length * ratio);
    const targetIndex =
      this.editorRefs.target?.selectionStart ?? Math.round(draft.target.length * ratio);
    const hasTarget = state.session?.target_lang != null;
    const response = await this.runMutation((base) =>
      this.api.split(selected.id, {
        base_revision: base,
        op_id: opId("split"),
        at,
        source_left: draft.source.slice(0, sourceIndex).trim(),
        source_right: draft.source.slice(sourceIndex).trim(),
        target_left: hasTarget ? draft.target.slice(0, targetIndex).trim() : null,
        target_right: hasTarget ? draft.target.slice(targetIndex).trim() : null,
      }),
    );
    if (response?.changed[1]) {
      this.store.setState({ selectedId: response.changed[1], selection: [response.changed[1]] });
    }
  }

  async mergeNext(): Promise<void> {
    const state = this.store.getState();
    const selected = findCue(state.cues, state.selectedId);
    if (!selected) return;
    const index = state.cues.findIndex((cue) => cue.id === selected.id);
    const next = state.cues[index + 1];
    if (!next) return;
    await this.runMutation((base) =>
      this.api.merge({ base_revision: base, op_id: opId("merge"), cue_ids: [selected.id, next.id] }),
    );
  }

  async insertAtPlayhead(): Promise<void> {
    const response = await this.runMutation((base) =>
      this.api.insert({
        base_revision: base,
        op_id: opId("insert"),
        at: this.player.getPlaybackTime(),
      }),
    );
    if (response?.changed[0]) {
      this.store.setState({ selectedId: response.changed[0], selection: [response.changed[0]] });
    }
  }

  async deleteSelected(): Promise<void> {
    const state = this.store.getState();
    const selected = findCue(state.cues, state.selectedId);
    if (!selected) return;
    const index = state.cues.findIndex((cue) => cue.id === selected.id);
    const response = await this.runMutation((base) =>
      this.api.deleteCue(selected.id, { base_revision: base, op_id: opId("delete") }),
    );
    if (response) {
      const next = response.cues[Math.min(index, response.cues.length - 1)] ?? null;
      this.store.setState({
        selectedId: next?.id ?? null,
        selection: next ? [next.id] : [],
      });
    }
  }

  async undo(): Promise<void> {
    await this.runMutation((base) => this.api.undo({ base_revision: base, op_id: opId("undo") }));
  }

  async redo(): Promise<void> {
    await this.runMutation((base) => this.api.redo({ base_revision: base, op_id: opId("redo") }));
  }

  async switchLanguage(value: string): Promise<void> {
    try {
      const base = await this.persistDraft();
      const response = await this.api.switchTarget({
        base_revision: base,
        op_id: opId("switch"),
        target_lang: value === "source" ? null : value,
      });
      this.store.setState({ session: response });
      this.applyResponse(response);
      const next =
        response.cues.find((cue) => cue.status === "unreviewed") ?? response.cues[0] ?? null;
      this.store.setState({
        selectedId: next?.id ?? null,
        selection: next ? [next.id] : [],
      });
    } catch (error) {
      this.handleError(error);
    }
  }

  // ------------------------------------------------------- issues (§7 cards)

  /** Dismiss one issue kind on a cue (persisted per §4.3). */
  async dismissIssue(cueId: number, kind: IssueKind): Promise<void> {
    await this.runMutation((base) =>
      this.api.dismissIssue(cueId, { base_revision: base, op_id: opId("dismiss"), kind }),
    );
  }

  // -------------------------------------------------------- suggestions (§7)

  /** Fill a suggestion's patch into the local draft — dirty edit, no mutation. */
  applySuggestionToDraft(suggestion: Suggestion): void {
    const state = this.store.getState();
    if (state.selectedId !== suggestion.cue_id || !state.draft) return;
    const { patch } = suggestion;
    this.updateDraft({
      ...(patch.source != null ? { source: patch.source } : {}),
      ...(patch.target != null ? { target: patch.target } : {}),
      ...(patch.start != null ? { start: patch.start } : {}),
      ...(patch.end != null ? { end: patch.end } : {}),
    });
  }

  async acceptSuggestion(id: string): Promise<void> {
    await this.runMutation((base) =>
      this.api.acceptSuggestion(id, { base_revision: base, op_id: opId("accept") }),
    );
  }

  async rejectSuggestion(id: string): Promise<void> {
    await this.runMutation((base) =>
      this.api.rejectSuggestion(id, { base_revision: base, op_id: opId("reject") }),
    );
  }

  async reopenSuggestion(id: string): Promise<void> {
    await this.runMutation((base) =>
      this.api.reopenSuggestion(id, { base_revision: base, op_id: opId("reopen") }),
    );
  }

  // ------------------------------------------------------------ batch (§7)

  /** Forced dry-run preview (§4.5): reads server state, mutates nothing. */
  async previewBatchReplace(params: BatchReplaceParams): Promise<BatchDryRunResult> {
    return this.api.batchPreview({
      base_revision: this.store.getState().revision,
      op_id: opId("batch-preview"),
      find: params.find,
      replace: params.replace,
      fields: params.fields,
      case_sensitive: params.caseSensitive,
      regex: params.regex,
      ...(params.cueIds?.length ? { cue_ids: params.cueIds } : {}),
    });
  }

  async executeBatchReplace(params: BatchReplaceParams): Promise<Snapshot | null> {
    return this.runMutation((base) =>
      this.api.batchReplace({
        base_revision: base,
        op_id: opId("batch-replace"),
        find: params.find,
        replace: params.replace,
        fields: params.fields,
        case_sensitive: params.caseSensitive,
        regex: params.regex,
        ...(params.cueIds?.length ? { cue_ids: params.cueIds } : {}),
      }),
    );
  }

  async batchStatus(cueIds: number[], status: ReviewStatus): Promise<void> {
    if (cueIds.length === 0) return;
    await this.runMutation((base) =>
      this.api.batchStatus({
        base_revision: base,
        op_id: opId("batch-status"),
        cue_ids: cueIds,
        status,
      }),
    );
  }

  async batchDelete(cueIds: number[]): Promise<void> {
    if (cueIds.length === 0) return;
    const state = this.store.getState();
    const indices = cueIds
      .map((id) => state.cues.findIndex((cue) => cue.id === id))
      .filter((index) => index >= 0);
    const anchorIndex = indices.length > 0 ? Math.min(...indices) : 0;
    const response = await this.runMutation((base) =>
      this.api.batchDelete({
        base_revision: base,
        op_id: opId("batch-delete"),
        cue_ids: cueIds,
      }),
    );
    if (response) {
      const next = response.cues[Math.min(anchorIndex, response.cues.length - 1)] ?? null;
      this.store.setState({
        selectedId: next?.id ?? null,
        selection: next ? [next.id] : [],
      });
    }
  }

  // ------------------------------------------------------------ glossary (§7)

  async addTerm(source: string, target: string, note?: string): Promise<boolean> {
    const trimmedSource = source.trim();
    const trimmedTarget = target.trim();
    if (!trimmedSource || !trimmedTarget) return false;
    try {
      const base = await this.persistDraft();
      this.store.setState({ saveState: "saving" });
      const response = await this.api.addGlossaryTerm({
        base_revision: base,
        op_id: opId("term"),
        source: trimmedSource,
        target: trimmedTarget,
        note: note?.trim() || null,
      });
      this.applyResponse(response);
      this.store.setState({ addTerm: null });
      this.showToast(
        this.t("glossary.success", { source: trimmedSource, target: trimmedTarget }),
      );
      return true;
    } catch (error) {
      this.handleError(error);
      return false;
    }
  }

  // ------------------------------------------------------------- selection

  /** Shift-click range select across the currently visible (filtered) order. */
  selectRange(targetId: number, orderedIds: number[]): void {
    const anchor = this.store.getState().selectedId;
    const anchorIndex = anchor != null ? orderedIds.indexOf(anchor) : -1;
    const targetIndex = orderedIds.indexOf(targetId);
    if (targetIndex < 0) return;
    if (anchorIndex < 0) {
      this.store.setState({ selection: [targetId] });
      return;
    }
    const [from, to] = anchorIndex <= targetIndex
      ? [anchorIndex, targetIndex]
      : [targetIndex, anchorIndex];
    this.store.setState({ selection: orderedIds.slice(from, to + 1) });
  }

  /** Ctrl/⌘-click toggles one cue in the selection set. */
  toggleInSelection(id: number): void {
    const state = this.store.getState();
    const selection = state.selection.includes(id)
      ? state.selection.filter((entry) => entry !== id)
      : [...state.selection, id];
    this.store.setState({ selection });
  }

  clearSelection(): void {
    const selectedId = this.store.getState().selectedId;
    this.store.setState({ selection: selectedId != null ? [selectedId] : [] });
  }
}

function nextUnreviewed(cues: Cue[], index: number): Cue | null {
  if (index < 0) return cues.find((cue) => cue.status === "unreviewed") ?? null;
  return (
    [...cues.slice(index + 1), ...cues.slice(0, index)].find(
      (cue) => cue.status === "unreviewed",
    ) ?? null
  );
}
