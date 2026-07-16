import { cn } from "@/lib/utils"

/*
 * status-dot from DESIGN-resend.md, remapped semantically to scan/site
 * health per §4: clean = green, pending/investigating = orange,
 * confirmed change = red, inactive/unknown = stone. 8px, full radius.
 */
export type DotState = "clean" | "pending" | "threat" | "idle"

const stateColor: Record<DotState, string> = {
  clean: "bg-accent-green",
  pending: "bg-accent-orange",
  threat: "bg-accent-red",
  idle: "bg-stone",
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
      className={cn("inline-block size-2 rounded-full", stateColor[state], className)}
    />
  )
}
