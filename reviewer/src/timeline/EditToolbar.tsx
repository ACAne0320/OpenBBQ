import { Combine, Plus, Redo2, Scissors, Trash2, Undo2 } from "lucide-react";
import { IconButton } from "@/components/icon-button";
import { useI18n } from "../app/i18n";
import { useServices } from "../app/services";

/** Structural cue editing: undo/redo, insert, split, merge, delete. */
export function EditToolbar() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  return (
    <div className="edit-toolbar">
      <IconButton label={t("action.undo")} shortcut="⌘Z" onClick={() => void commands.undo()}>
        <Undo2 />
      </IconButton>
      <IconButton label={t("action.redo")} shortcut="⇧⌘Z" onClick={() => void commands.redo()}>
        <Redo2 />
      </IconButton>
      <span className="toolbar-separator" />
      <IconButton label={t("action.insert")} onClick={() => void commands.insertAtPlayhead()}>
        <Plus />
      </IconButton>
      <IconButton label={t("action.split")} shortcut="S" onClick={() => void commands.splitCurrent()}>
        <Scissors />
      </IconButton>
      <IconButton label={t("action.merge")} onClick={() => void commands.mergeNext()}>
        <Combine />
      </IconButton>
      <IconButton
        label={t("action.delete")}
        variant="destructive"
        onClick={() => store.setState({ deleteOpen: true })}
      >
        <Trash2 />
      </IconButton>
    </div>
  );
}
