import { useEffect, useState } from "react";
import { BookMarked } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "../app/i18n";
import { useAppSelector, useServices } from "../app/services";

/**
 * Add-term dialog (§7): prefilled from a textarea selection or a term issue
 * card. Submitting writes to the workspace glossary; the response's
 * recomputed issues clear related term warnings across the corpus.
 */
export function AddTermDialog() {
  const { t } = useI18n();
  const { store, commands } = useServices();
  const addTerm = useAppSelector((state) => state.addTerm);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (addTerm) {
      setSource(addTerm.source);
      setTarget(addTerm.target);
      setNote(addTerm.note);
    }
  }, [addTerm]);

  const close = () => store.setState({ addTerm: null });
  const valid = source.trim().length > 0 && target.trim().length > 0;

  return (
    <AlertDialog open={addTerm != null} onOpenChange={(open) => !open && close()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            <BookMarked aria-hidden="true" /> {t("glossary.addTerm")}
          </AlertDialogTitle>
          <AlertDialogDescription>{t("glossary.description")}</AlertDialogDescription>
        </AlertDialogHeader>
        <div className="term-form">
          <label>
            <span>{t("glossary.sourceTerm")}</span>
            <Input
              value={source}
              aria-label={t("glossary.sourceTerm")}
              onChange={(event) => setSource(event.target.value)}
            />
          </label>
          <label>
            <span>{t("glossary.targetTerm")}</span>
            <Input
              value={target}
              aria-label={t("glossary.targetTerm")}
              onChange={(event) => setTarget(event.target.value)}
            />
          </label>
          <label>
            <span>{t("glossary.note")}</span>
            <Input
              value={note}
              aria-label={t("glossary.note")}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
        </div>
        <AlertDialogFooter>
          <Button variant="outline" onClick={close}>
            {t("action.cancel")}
          </Button>
          <Button
            disabled={!valid || busy}
            onClick={() => {
              setBusy(true);
              void commands.addTerm(source, target, note).finally(() => setBusy(false));
            }}
          >
            {t("glossary.submit")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
