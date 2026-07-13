import type { ComponentProps, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface IconButtonProps extends ComponentProps<typeof Button> {
  label: string;
  shortcut?: ReactNode;
}

export function IconButton({ label, shortcut, ...props }: IconButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger render={<Button aria-label={label} size="icon" variant="ghost" {...props} />} />
      <TooltipContent>
        {label}
        {shortcut && <span className="tooltip-shortcut">{shortcut}</span>}
      </TooltipContent>
    </Tooltip>
  );
}
