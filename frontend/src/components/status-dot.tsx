import { cn } from "@/lib/utils"

/*
 * status-dot from DESIGN-resend.md, remapped semantically to scan/site
 * health per §4: clean = green, pending/investigating = orange,
 * confirmed change = red, inactive/unknown = stone. 8px, full radius.
 */
export type DotState = "clean" | "pending" | "threat" | "idle"

const stateClass: Record<DotState, string> = {
  clean: "status-dot-clean",
  pending: "status-dot-pending",
  threat: "status-dot-threat",
  idle: "status-dot-idle",
}

export function StatusDot({
  state,
  className,
}: {
  state: DotState
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 rounded-full", stateClass[state], className)}
    />
  )
}
