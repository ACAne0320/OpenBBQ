import { useRef } from "react";
import { useI18n, type MessageKey } from "./i18n";
import { useServices } from "./services";
import { updatePrefs } from "../store/prefs";

interface ResizerProps {
  /** Which pane this handle resizes. */
  side: "list" | "editor";
}

const LIMITS: Record<ResizerProps["side"], { min: number; max: number }> = {
  list: { min: 240, max: 560 },
  editor: { min: 300, max: 560 },
};

const LABELS: Record<ResizerProps["side"], MessageKey> = {
  list: "layout.resizeList",
  editor: "layout.resizeEditor",
};

/** Pointer-based column resizer; widths persist via the prefs slice. */
export function Resizer({ side }: ResizerProps) {
  const { t } = useI18n();
  const { store } = useServices();
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const widthKey = side === "list" ? "listWidth" : "editorWidth";

  return (
    <div
      className="pane-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label={t(LABELS[side])}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        dragRef.current = {
          startX: event.clientX,
          startWidth: store.getState().prefs[widthKey],
        };
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag) return;
        const delta = event.clientX - drag.startX;
        const { min, max } = LIMITS[side];
        const next =
          side === "list" ? drag.startWidth + delta : drag.startWidth - delta;
        updatePrefs(store, { [widthKey]: Math.round(Math.max(min, Math.min(max, next))) });
      }}
      onPointerUp={(event) => {
        dragRef.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={() => {
        dragRef.current = null;
      }}
    />
  );
}
