import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/*
 * Wardress reskin — DESIGN-resend.md badge-pill spec: surface-elevated
 * background, body text color, caption type, full radius, 4x10 padding.
 * Threat-state variants (§4 Wardress additions) tint TEXT with the accent
 * color at readable strength and keep the fill as a low-opacity wash —
 * accents are never solid fills.
 */
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-2.5 py-1 text-caption whitespace-nowrap transition-colors [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-surface-elevated text-body",
        secondary: "bg-surface-elevated text-charcoal",
        outline: "border-hairline-strong bg-transparent text-body",
        // Threat states — glow-strength washes, accent text, never solid
        clean: "bg-glow-green text-accent-green",
        pending: "bg-glow-orange text-accent-orange",
        threat: "bg-glow-red text-accent-red",
        ghost: "text-charcoal",
        link: "text-link underline-offset-4 [a&]:hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
