import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Locale = "en" | "zh";

const messages = {
  en: {
    "app.loading": "Opening review workspace…",
    "app.reviewLanguage": "Subtitle language",
    "app.sourceOnly": "Source only",
    "app.cueList": "Subtitle cue review list",
    "app.reloadDiscard": "Discard edits and reload",
    "app.mediaTimeline": "Media preview and subtitle timeline",
    "app.saved": "Saved",
    "app.saving": "Saving",
    "app.saveFailed": "Save failed",
    "app.conflict": "External conflict",
    "app.progress": "Reviewed {reviewed}/{total}",
    "app.flaggedProgress": "{count} flagged",
    "app.themeLight": "Use light theme",
    "app.themeDark": "Use dark theme",
    "app.locale": "Interface language",
    "app.localeEnglish": "Switch interface to English",
    "app.localeChinese": "Switch interface to Chinese",
    "app.proxyTitle": "Preparing a browser-compatible preview",
    "app.proxyDescription": "The original container or codec cannot play in this browser. OpenBBQ is creating an H.264/AAC review proxy; cue editing remains available.",
    "app.transcoding": "FFmpeg is transcoding…",
    "app.retryProxy": "Retry preview",
    "app.audio": "Audio review",
    "transport.controls": "Playback controls",
    "transport.skipBack": "Back 5 seconds",
    "transport.play": "Play",
    "transport.pause": "Pause",
    "transport.skipForward": "Forward 5 seconds",
    "transport.progress": "Playback progress",
    "transport.volume": "Volume",
    "transport.mute": "Mute",
    "transport.unmute": "Unmute",
    "transport.fullscreen": "Fullscreen",
    "transport.speed": "Playback speed",
    "transport.loop": "Loop current cue",
    "transport.subtitles": "Subtitle display",
    "overlay.bilingual": "Bilingual",
    "overlay.target": "Translation",
    "overlay.source": "Source",
    "overlay.hidden": "Hidden",
    "timeline.title": "Waveform · Cue Track",
    "timeline.hint": "Drag cue edges to trim. Drag the center to move.",
    "timeline.zoomOut": "Zoom out",
    "timeline.zoomIn": "Zoom in",
    "timeline.expand": "Expand timeline",
    "timeline.collapse": "Collapse timeline",
    "timeline.snap": "Snap",
    "timeline.snapOn": "Snapping on",
    "timeline.snapOff": "Snapping off",
    "timeline.fitCue": "Fit selected cue",
    "timeline.nudgeEarlier": "Move selected cue earlier",
    "timeline.nudgeLater": "Move selected cue later",
    "timeline.nudgeStartEarlier": "Move start earlier",
    "timeline.nudgeStartLater": "Move start later",
    "timeline.nudgeEndEarlier": "Move end earlier",
    "timeline.nudgeEndLater": "Move end later",
    "timeline.step": "Nudge step",
    "timeline.start": "Start",
    "timeline.end": "End",
    "timeline.duration": "Duration",
    "timeline.selectedCue": "Selected cue",
    "timeline.aria": "Subtitle waveform timeline. Click to seek, drag cue edges to trim, or drag the cue center to move it.",
    "action.undo": "Undo",
    "action.redo": "Redo",
    "action.insert": "Add cue at playhead",
    "action.split": "Split cue at playhead",
    "action.merge": "Merge with next cue",
    "action.delete": "Delete cue",
    "action.review": "Reviewed",
    "action.flag": "Flag",
    "action.moreFilters": "Quality filters",
    "action.backToPlayback": "Resume follow",
    "filter.unreviewed": "Unreviewed",
    "filter.reviewed": "Reviewed",
    "filter.flagged": "Flagged",
    "filter.all": "All",
    "filter.missing": "Missing translation",
    "filter.overBudget": "Over budget",
    "filter.timeWarning": "Timing issue",
    "filter.termWarning": "Term warning",
    "filter.search": "Search or #ID",
    "filter.follow": "Follow playback",
    "filter.following": "Following playback",
    "filter.empty": "No cues match this view.",
    "cue.blank": "Empty cue",
    "cue.source": "Source",
    "cue.translation": "{language} translation",
    "cue.translationField": "Translation",
    "cue.sourceOnlyHint": "Choose a subtitle language to add a translation.",
    "cue.note": "Review note",
    "cue.notePlaceholder": "Record a question or reason for the edit",
    "cue.sourceCps": "Source {value} chars/s",
    "cue.budget": "{used}/{limit} chars",
    "cue.overBudget": "Translation exceeds the current timing budget. Shorten it or extend the cue.",
    "cue.status.unreviewed": "Unreviewed",
    "cue.status.reviewed": "Reviewed",
    "cue.status.flagged": "Flagged",
    "warning.overBudget": "Over limit",
    "warning.time": "Timing issue",
    "warning.term": "Term",
    "warning.overBudgetHint": "The translation exceeds this cue's character limit.",
    "warning.timeHint": "Check this cue's start, end, or spacing.",
    "warning.termHint": "Check the terminology in this cue.",
    "error.split": "Place the playhead inside the selected cue before splitting.",
    "error.deleteConfirm": "Delete cue #{id}? You can undo immediately.",
    "error.conflict": "The workspace changed in another command or tab. Autosave is paused. Copy any local text you need, then discard these edits and reload the latest version.",
    "error.unknown": "Unknown error",
  },
  zh: {
    "app.loading": "正在打开审核 workspace…",
    "app.reviewLanguage": "字幕语言",
    "app.sourceOnly": "仅原文",
    "app.cueList": "字幕审核列表",
    "app.reloadDiscard": "放弃修改并重新加载",
    "app.mediaTimeline": "媒体预览和字幕时间线",
    "app.saved": "已保存",
    "app.saving": "正在保存",
    "app.saveFailed": "保存失败",
    "app.conflict": "外部冲突",
    "app.progress": "已审核 {reviewed}/{total}",
    "app.flaggedProgress": "{count} 待处理",
    "app.themeLight": "切换浅色主题",
    "app.themeDark": "切换深色主题",
    "app.locale": "界面语言",
    "app.localeEnglish": "切换到英文界面",
    "app.localeChinese": "切换到中文界面",
    "app.proxyTitle": "正在准备浏览器兼容预览",
    "app.proxyDescription": "原媒体容器或编码无法直接在浏览器播放。OpenBBQ 正在生成 H.264/AAC 审核 proxy；cue 编辑仍可使用。",
    "app.transcoding": "FFmpeg 转码中…",
    "app.retryProxy": "重试生成预览",
    "app.audio": "音频审核",
    "transport.controls": "播放控制",
    "transport.skipBack": "后退 5 秒",
    "transport.play": "播放",
    "transport.pause": "暂停",
    "transport.skipForward": "前进 5 秒",
    "transport.progress": "播放进度",
    "transport.volume": "音量",
    "transport.mute": "静音",
    "transport.unmute": "取消静音",
    "transport.fullscreen": "全屏",
    "transport.speed": "播放速度",
    "transport.loop": "循环当前 cue",
    "transport.subtitles": "字幕显示",
    "overlay.bilingual": "双语",
    "overlay.target": "译文",
    "overlay.source": "原文",
    "overlay.hidden": "隐藏",
    "timeline.title": "波形 · 字幕轨",
    "timeline.hint": "拖动边缘微调时间，拖动中部整体移动。",
    "timeline.zoomOut": "缩小时间线",
    "timeline.zoomIn": "放大时间线",
    "timeline.expand": "展开时间线",
    "timeline.collapse": "收起时间线",
    "timeline.snap": "吸附",
    "timeline.snapOn": "已开启吸附",
    "timeline.snapOff": "已关闭吸附",
    "timeline.fitCue": "聚焦当前 cue",
    "timeline.nudgeEarlier": "当前 cue 向前移动",
    "timeline.nudgeLater": "当前 cue 向后移动",
    "timeline.nudgeStartEarlier": "开始时间提前",
    "timeline.nudgeStartLater": "开始时间延后",
    "timeline.nudgeEndEarlier": "结束时间提前",
    "timeline.nudgeEndLater": "结束时间延后",
    "timeline.step": "微调步长",
    "timeline.start": "开始",
    "timeline.end": "结束",
    "timeline.duration": "时长",
    "timeline.selectedCue": "当前 cue",
    "timeline.aria": "字幕波形时间线。点击定位，拖动字幕条边缘微调，拖动中部整体移动。",
    "action.undo": "撤销",
    "action.redo": "重做",
    "action.insert": "在播放头新增 cue",
    "action.split": "在播放头拆分 cue",
    "action.merge": "与下一条合并",
    "action.delete": "删除 cue",
    "action.review": "标为已审核",
    "action.flag": "待处理",
    "action.moreFilters": "质量筛选",
    "action.backToPlayback": "恢复跟随",
    "filter.unreviewed": "未审核",
    "filter.reviewed": "已审核",
    "filter.flagged": "待处理",
    "filter.all": "全部",
    "filter.missing": "未翻译",
    "filter.overBudget": "超预算",
    "filter.timeWarning": "时间问题",
    "filter.termWarning": "术语警告",
    "filter.search": "搜索或 #ID",
    "filter.follow": "跟随播放",
    "filter.following": "跟随播放中",
    "filter.empty": "没有符合当前筛选的 cue。",
    "cue.blank": "空 cue",
    "cue.source": "原文",
    "cue.translation": "{language} 译文",
    "cue.translationField": "译文",
    "cue.sourceOnlyHint": "选择字幕语言后可编辑译文。",
    "cue.note": "审核备注",
    "cue.notePlaceholder": "记录待确认的问题或修改原因",
    "cue.sourceCps": "原文 {value} 字/秒",
    "cue.budget": "{used}/{limit} 字",
    "cue.overBudget": "译文超过当前时长预算，建议缩短译文或延长 cue。",
    "cue.status.unreviewed": "未审核",
    "cue.status.reviewed": "已审核",
    "cue.status.flagged": "待处理",
    "warning.overBudget": "超字数",
    "warning.time": "时间问题",
    "warning.term": "术语",
    "warning.overBudgetHint": "译文超过当前字幕的字数限制。",
    "warning.timeHint": "请检查当前字幕的开始、结束或间隔。",
    "warning.termHint": "请检查当前字幕中的术语。",
    "error.split": "播放头必须位于当前 cue 内部才能拆分。",
    "error.deleteConfirm": "删除 cue #{id}？可以立即撤销。",
    "error.conflict": "workspace 已被其他命令或页面修改，自动保存已暂停。请先复制需要保留的本地文字，再放弃当前修改并加载最新版本。",
    "error.unknown": "未知错误",
  },
} as const;

export type MessageKey = keyof (typeof messages)["en"];

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nValue | null>(null);
const STORAGE_KEY = "openbbq-review-locale";

function browserLocale(): Locale {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "en" || stored === "zh") return stored;
  return window.navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function I18nProvider({
  children,
  initialLocale,
}: {
  children: ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, setLocaleState] = useState<Locale>(() => initialLocale ?? browserLocale());

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  const setLocale = useCallback((nextLocale: Locale) => {
    window.localStorage.setItem(STORAGE_KEY, nextLocale);
    setLocaleState(nextLocale);
  }, []);

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale,
      t: (key, values) => {
        const message: string = messages[locale][key];
        if (!values) return message;
        return Object.entries(values).reduce<string>(
          (result, [name, value]) => result.replaceAll(`{${name}}`, String(value)),
          message,
        );
      },
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}
