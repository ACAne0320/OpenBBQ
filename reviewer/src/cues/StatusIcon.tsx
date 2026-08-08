import { CheckCircle2, Circle, Flag } from "lucide-react";
import type { ReviewStatus } from "../api/types";

export function StatusIcon({ status }: { status: ReviewStatus }) {
  if (status === "reviewed") {
    return <CheckCircle2 className="status-icon reviewed" aria-hidden="true" />;
  }
  if (status === "flagged") return <Flag className="status-icon flagged" aria-hidden="true" />;
  return <Circle className="status-icon unreviewed" aria-hidden="true" />;
}
