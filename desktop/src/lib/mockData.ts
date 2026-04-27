import type { ReviewModel, TaskMonitorModel, WorkflowStep } from "./types.js";

export const workflowSteps: WorkflowStep[] = [
  {
    id: "extract_audio",
    name: "Extract Audio",
    toolRef: "ffmpeg.extract_audio",
    summary: "video -> audio",
    status: "locked",
    parameters: [
      { kind: "select", key: "format", label: "Format", value: "wav", options: ["wav"] },
      { kind: "text", key: "sample_rate", label: "Sample rate", value: "16000" }
    ]
  },
  {
    id: "transcribe",
    name: "Transcribe",
    toolRef: "faster_whisper.transcribe",
    summary: "audio -> transcript",
    status: "locked",
    selected: true,
    parameters: [
      { kind: "select", key: "language", label: "Language", value: "English", options: ["English", "Auto"] },
      { kind: "select", key: "model", label: "Model", value: "base", options: ["tiny", "base", "small", "medium"] },
      { kind: "select", key: "device", label: "Device", value: "cpu", options: ["cpu", "cuda"] },
      { kind: "select", key: "compute_type", label: "Compute", value: "int8", options: ["int8", "float16", "float32"] },
      {
        kind: "toggle",
        key: "word_timestamps",
        label: "Word timestamps",
        description: "Include word-level timing details.",
        value: true
      },
      {
        kind: "toggle",
        key: "vad_filter",
        label: "VAD filter",
        description: "Filter non-speech sections before transcription.",
        value: true
      }
    ]
  },
  {
    id: "correct",
    name: "Correct Transcript",
    toolRef: "transcript.correct",
    summary: "cleanup before segmentation",
    status: "enabled",
    parameters: [
      { kind: "text", key: "source_lang", label: "Source language", value: "en" },
      { kind: "text", key: "temperature", label: "Temperature", value: "0" }
    ]
  },
  {
    id: "segment",
    name: "Segment Subtitle",
    toolRef: "transcript.segment",
    summary: "transcript -> subtitle segments",
    status: "locked",
    parameters: [
      { kind: "text", key: "max_duration_seconds", label: "Max duration seconds", value: "6" },
      { kind: "text", key: "max_lines", label: "Max lines", value: "2" }
    ]
  },
  {
    id: "translate",
    name: "Translate Subtitle",
    toolRef: "translation.translate",
    summary: "segments -> translation",
    status: "locked",
    parameters: [
      { kind: "text", key: "source_lang", label: "Source language", value: "en" },
      { kind: "text", key: "target_lang", label: "Target language", value: "zh" }
    ]
  },
  {
    id: "subtitle",
    name: "Export Subtitle",
    toolRef: "subtitle.export",
    summary: "translation -> SRT",
    status: "locked",
    parameters: [{ kind: "select", key: "format", label: "Format", value: "srt", options: ["srt"] }]
  }
];

export const failedTask: TaskMonitorModel = {
  id: "run_sample",
  title: "sample-interview",
  workflowName: "Local video -> translated SRT",
  status: "failed",
  errorMessage: "Translation provider failed. Fix the cause, then retry from the latest completed checkpoint.",
  progress: [
    { id: "extract_audio", label: "Extract", status: "done" },
    { id: "transcribe", label: "Transcribe", status: "done" },
    { id: "segment", label: "Segment", status: "done" },
    { id: "translate", label: "Translate", status: "failed" },
    { id: "subtitle", label: "Export", status: "blocked" }
  ],
  logs: [
    {
      sequence: 1,
      timestamp: "2026-04-27T03:15:12.000Z",
      level: "info",
      message: "Task started for sample-interview."
    },
    {
      sequence: 2,
      timestamp: "2026-04-27T03:15:18.000Z",
      level: "info",
      message: "Audio extraction completed."
    },
    {
      sequence: 3,
      timestamp: "2026-04-27T03:16:44.000Z",
      level: "info",
      message: "Transcription completed with 42 segments."
    },
    {
      sequence: 4,
      timestamp: "2026-04-27T03:17:02.000Z",
      level: "info",
      message: "Subtitle segmentation completed."
    },
    {
      sequence: 5,
      timestamp: "2026-04-27T03:17:09.000Z",
      level: "error",
      message: "Translation provider failed: provider returned rate limit at checkpoint translate."
    }
  ]
};

const waveformLevels = [24, 40, 62, 48, 72, 56, 80, 34];

export const reviewModel: ReviewModel = {
  title: "sample-interview",
  durationMs: 228420,
  currentMs: 12100,
  activeSegmentId: "seg-03",
  waveform: Array.from({ length: 48 }, (_, index) => ({
    id: `bar-${index.toString().padStart(2, "0")}`,
    level: waveformLevels[index % waveformLevels.length]
  })),
  segments: [
    {
      id: "seg-02",
      index: 2,
      startMs: 8400,
      endMs: 11980,
      transcript: "The subtitle file will be generated after review.",
      translation: "The reviewed subtitle file will be generated after approval.",
      savedState: "saved"
    },
    {
      id: "seg-03",
      index: 3,
      startMs: 12100,
      endMs: 16580,
      transcript: "Each result is saved as an editable versioned segment.",
      translation: "Each result is saved as an editable versioned segment.",
      savedState: "saving"
    },
    {
      id: "seg-04",
      index: 4,
      startMs: 17120,
      endMs: 21940,
      transcript: "You can export the final SRT once the result looks right.",
      translation: "Export the final SRT after the result is reviewed.",
      savedState: "saved"
    }
  ]
};
