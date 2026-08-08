import { Check, Circle, Flag, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";

/**
 * Batch bar (§7): appears when more than one cue is selected. Status marks
 * go through batchStatus; delete asks for confirmation and goes through the
 * atomic batch-delete endpoint (one undo restores the whole batch).
 */
export function BatchBar({ onDelete }: { onDelete: () => void }) {
  const { t } = useI18n();
  const { commands } = useServices();
  const selection = useAppSelector((state) => state.selection);

  if (selection.length <= 1) return null;
  return (
    <div className="batch-bar" role="group" aria-label={t("batch.selected", { count: selection.length })}>
      <strong>{t("batch.selected", { count: selection.length })}</strong>
      <Button
        size="sm"
        variant="outline"
        onClick={() => void commands.batchStatus(selection, "reviewed")}
      >
        <Check />
        {t("batch.markReviewed")}
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={() => void commands.batchStatus(selection, "flagged")}
      >
        <Flag />
        {t("batch.markFlagged")}
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={() => void commands.batchStatus(selection, "unreviewed")}
      >
        <Circle />
        {t("batch.markUnreviewed")}
      </Button>
      <Button size="sm" variant="destructive" onClick={onDelete}>
        <Trash2 />
        {t("batch.delete")}
      </Button>
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={t("batch.clear")}
        onClick={() => commands.clearSelection()}
      >
        <X />
      </Button>
    </div>
  );
}
