import * as React from "react"

import { cn } from "@/lib/utils"

/*
 * Wardress reskin — DESIGN-resend.md text-input spec: surface-card
 * background, ink text, body-sm type, hairline-strong 1px border, 8px
 * radius, 10x14 padding, 40px height. Focus thickens the border to ink —
 * no separate ring color, no shadow.
 */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-10 w-full min-w-0 rounded-md border border-hairline-strong bg-surface-card px-3.5 py-2.5 text-body-sm text-ink transition-colors outline-none selection:bg-ink selection:text-canvas placeholder:text-mute disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "focus-visible:border-ink",
        "aria-invalid:border-accent-red",
        className
      )}
      {...props}
    />
  )
}

export { Input }
