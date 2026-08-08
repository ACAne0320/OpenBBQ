/**
 * MM:SS.mmm time formatting with tolerant parsing (design §6.1):
 * accepts "1:23.456", "83.456", "1:23", "1:02:03.500"; rejects garbage.
 */

const PLAIN = /^(\d+(?:\.\d{1,3})?)$/;
const MIN_SEC = /^(\d+):([0-5]?\d(?:\.\d{1,3})?)$/;
const HOUR_MIN_SEC = /^(\d+):([0-5]?\d):([0-5]?\d(?:\.\d{1,3})?)$/;

/** Parses tolerant time input into seconds, or null when invalid. */
export function parseTimeInput(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  let seconds: number;
  const plain = PLAIN.exec(trimmed);
  const hour = HOUR_MIN_SEC.exec(trimmed);
  const minute = MIN_SEC.exec(trimmed);
  if (hour) {
    seconds = Number(hour[1]) * 3600 + Number(hour[2]) * 60 + Number(hour[3]);
  } else if (minute) {
    seconds = Number(minute[1]) * 60 + Number(minute[2]);
  } else if (plain) {
    seconds = Number(plain[1]);
  } else {
    return null;
  }
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return Number(seconds.toFixed(3));
}

/** Formats seconds as MM:SS.mmm (with an hour segment when needed). */
export function formatTimeInput(seconds: number): string {
  const safe = Math.max(0, seconds);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const rest = safe % 60;
  const minuteTime = `${String(minutes).padStart(2, "0")}:${rest.toFixed(3).padStart(6, "0")}`;
  return hours > 0 ? `${String(hours).padStart(2, "0")}:${minuteTime}` : minuteTime;
}
