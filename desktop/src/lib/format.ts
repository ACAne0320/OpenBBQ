export function formatTimestamp(ms: number): string {
  const normalizedMs = Number.isFinite(ms) ? Math.max(0, Math.floor(ms)) : 0;
  const totalSeconds = Math.floor(normalizedMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const millis = normalizedMs % 1000;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}.${millis
    .toString()
    .padStart(3, "0")}`;
}

export function formatRange(startMs: number, endMs: number): string {
  return `${formatTimestamp(startMs)} -> ${formatTimestamp(endMs)}`;
}
