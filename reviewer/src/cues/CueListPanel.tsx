import { useEffect, useRef, useState } from "react";
import { Filter, ListFilter, LocateFixed, Search } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { IssueBadges } from "../issues/IssueBadge";
import { IssuesView } from "../issues/IssuesView";
import { useI18n, type MessageKey } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";
import { updatePrefs } from "../store/prefs";
import {
  selectActiveCueId,
  selectFilteredCues,
  selectIssueCounts,
} from "../store/selectors";
import type { CueFilter } from "../store/state";
import { BatchBar } from "./BatchBar";
import { FindReplacePanel } from "./FindReplacePanel";
import { StatusIcon } from "./StatusIcon";
import type { Cue } from "../api/types";

export const CUE_ROW_HEIGHT = 56;
const OVERSCAN = 6;

function shortTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds % 60).toFixed(3).padStart(6, "0");
  return `${String(minutes).padStart(2, "0")}:${rest}`;
}

function formatDuration(seconds: number) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}

const QUALITY_FILTERS = ["missing", "over_budget", "time_warning", "term_warning"] as const;

const QUALITY_LABELS: Record<(typeof QUALITY_FILTERS)[number], MessageKey> = {
  missing: "filter.missing",
  over_budget: "filter.overBudget",
  time_warning: "filter.timeWarning",
  term_warning: "filter.termWarning",
};

/** Left zone: dual view (list / issues), multi-select, batch bar (§7). */
export function CueListPanel() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const leftTab = useAppSelector((state) => state.prefs.leftTab);
  const findOpen = useAppSelector((state) => state.findOpen);
  const issueCounts = useAppSelector(selectIssueCounts);
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);

  return (
    <>
      {findOpen && <FindReplacePanel />}
      <div className="list-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={leftTab === "list"}
          className={leftTab === "list" ? "active" : undefined}
          onClick={() => updatePrefs(store, { leftTab: "list" })}
        >
          {t("tabs.list")}
        </button>
        <button
          role="tab"
          aria-selected={leftTab === "issues"}
          className={leftTab === "issues" ? "active" : undefined}
          onClick={() => updatePrefs(store, { leftTab: "issues" })}
        >
          <ListFilter aria-hidden="true" />
          {t("tabs.issues")}
          {issueCounts.total > 0 && <span className="tab-count">{issueCounts.total}</span>}
        </button>
      </div>
      {leftTab === "list" ? <CueListView /> : <IssuesView />}
      <BatchBar onDelete={() => setBatchDeleteOpen(true)} />
      <BatchDeleteDialog
        open={batchDeleteOpen}
        onOpenChange={setBatchDeleteOpen}
      />
    </>
  );
}

function BatchDeleteDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { commands } = useServices();
  const selection = useAppSelector((state) => state.selection);
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("batch.delete")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("batch.deleteConfirm", { count: selection.length })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("action.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              onOpenChange(false);
              void commands.batchDelete(selection);
            }}
          >
            {t("batch.delete")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function CueListView() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const filter = useAppSelector((state) => state.prefs.filter);
  const search = useAppSelector((state) => state.search);
  const viewDetached = useAppSelector((state) => state.viewDetached);
  const progress = useAppSelector((state) => state.progress);
  const filtered = useAppSelector(selectFilteredCues);
  const selectedId = useAppSelector((state) => state.selectedId);
  const selection = useAppSelector((state) => state.selection, shallowArrayEqual);
  const activeCueId = useAppSelector(selectActiveCueId);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(480);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      setViewportHeight(Math.max(1, Math.round(entry.contentRect.height)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Keep the selected row visible inside the virtual window unless the user
  // scrolled the list away (viewDetached); selection-follow is unaffected.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || viewDetached || selectedId == null) return;
    const index = filtered.findIndex((cue) => cue.id === selectedId);
    if (index < 0) return;
    const top = index * CUE_ROW_HEIGHT;
    const bottom = top + CUE_ROW_HEIGHT;
    if (top < node.scrollTop) node.scrollTop = top;
    else if (bottom > node.scrollTop + node.clientHeight) {
      node.scrollTop = bottom - node.clientHeight;
    }
  }, [viewDetached, selectedId, filtered]);

  const primaryFilters: Array<[CueFilter, string, number]> = [
    ["unreviewed", t("filter.unreviewed"), progress.unreviewed],
    ["reviewed", t("filter.reviewed"), progress.reviewed],
    ["flagged", t("filter.flagged"), progress.flagged],
    ["all", t("filter.all"), progress.total],
  ];

  const orderedIds = filtered.map((cue) => cue.id);
  const startIndex = Math.max(0, Math.floor(scrollTop / CUE_ROW_HEIGHT) - OVERSCAN);
  const endIndex = Math.min(
    filtered.length,
    Math.ceil((scrollTop + viewportHeight) / CUE_ROW_HEIGHT) + OVERSCAN,
  );
  const visible = filtered.slice(startIndex, endIndex);

  return (
    <>
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
              onClick={() => updatePrefs(store, { filter: value })}
            >
              <span>{label}</span>
              <span className="filter-count">{count}</span>
            </Button>
          ))}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  size="icon-sm"
                  variant={QUALITY_FILTERS.some((value) => value === filter) ? "secondary" : "ghost"}
                  aria-label={t("action.moreFilters")}
                  title={t("action.moreFilters")}
                />
              }
            >
              <Filter />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuRadioGroup
                value={filter}
                onValueChange={(value) => updatePrefs(store, { filter: value as CueFilter })}
              >
                {QUALITY_FILTERS.map((value) => (
                  <DropdownMenuRadioItem key={value} value={value}>
                    {t(QUALITY_LABELS[value])}
                  </DropdownMenuRadioItem>
                ))}
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
            onChange={(event) => store.setState({ search: event.target.value })}
          />
          <Button
            className="follow-button"
            size="sm"
            variant={viewDetached ? "outline" : "secondary"}
            aria-pressed={!viewDetached}
            onClick={() => {
              if (viewDetached) {
                store.setState({ viewDetached: false });
                if (activeCueId != null) commands.setSelected(activeCueId);
                return;
              }
              store.setState({ viewDetached: true });
            }}
          >
            <LocateFixed />
            <span>{viewDetached ? t("action.backToPlayback") : t("filter.following")}</span>
          </Button>
        </div>
      </div>

      <div className="cue-grid cue-table-head" aria-hidden="true">
        <span />
        <span>#</span>
        <span>
          {t("timeline.in")} / {t("timeline.out")}
        </span>
        <span>{t("timeline.duration")}</span>
        <span>{t("cue.source")}</span>
        <span />
      </div>
      <div
        className="cue-list"
        ref={scrollRef}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        onWheel={() => {
          if (!viewDetached) {
            store.setState({ viewDetached: true });
            commands.showToast(t("filter.followPaused"));
          }
        }}
      >
        <div
          className="cue-list-spacer"
          style={{ height: filtered.length * CUE_ROW_HEIGHT }}
        >
          {filtered.length === 0 && <div className="empty-state">{t("filter.empty")}</div>}
          {visible.map((cue, offset) => (
            <CueRow
              key={cue.id}
              cue={cue}
              top={(startIndex + offset) * CUE_ROW_HEIGHT}
              selected={cue.id === selectedId}
              multiSelected={selection.length > 1 && selection.includes(cue.id)}
              onSelect={(event) => {
                if (event.shiftKey) {
                  commands.selectRange(cue.id, orderedIds);
                } else if (event.ctrlKey || event.metaKey) {
                  commands.toggleInSelection(cue.id);
                } else {
                  void commands.selectCue(cue);
                }
              }}
            />
          ))}
        </div>
      </div>
    </>
  );
}

function CueRow({
  cue,
  top,
  selected,
  multiSelected,
  onSelect,
}: {
  cue: Cue;
  top: number;
  selected: boolean;
  multiSelected: boolean;
  onSelect: (event: React.MouseEvent) => void;
}) {
  const { t } = useI18n();
  return (
    <article
      className={`cue-row ${selected ? "selected" : ""} ${multiSelected ? "multi-selected" : ""} status-${cue.status}`}
      style={{ transform: `translateY(${top}px)` }}
    >
      <button className="cue-grid cue-summary" onClick={onSelect}>
        <StatusIcon status={cue.status} />
        <strong>{cue.id}</strong>
        <span className="cue-time">
          <b>{shortTime(cue.start)}</b>
          <b>{shortTime(cue.end)}</b>
        </span>
        <span className="cue-duration">{formatDuration(cue.duration)}</span>
        <span className="cue-preview">
          <b>{cue.source || t("cue.blank")}</b>
          {cue.target && <span>{cue.target}</span>}
        </span>
        <IssueBadges issues={cue.issues} />
      </button>
    </article>
  );
}

function shallowArrayEqual(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((entry, index) => entry === b[index]);
}
