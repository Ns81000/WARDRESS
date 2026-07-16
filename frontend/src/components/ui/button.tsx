import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/*
 * Wardress reskin of shadcn button — DESIGN-resend.md component specs:
 *   button-primary: white surface (#fcfdff), black label, 8px radius,
 *     36px height, 8x16 padding, Inter 14/500; pressed state drops to
 *     surface-light (#f1f7fe). The single brightest pixel per viewport.
 *   button-ghost: surface-elevated + hairline-strong border, ink label.
 *   button-outline: canvas background + hairline-strong border, ink label.
 * No drop shadows anywhere — hairlines carry depth on this canvas.
 */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-button-md whitespace-nowrap transition-colors outline-none focus-visible:border-ink focus-visible:ring-2 focus-visible:ring-ink/30 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground active:bg-surface-light hover:bg-surface-light",
        destructive:
          "border border-hairline-strong bg-canvas text-accent-red hover:bg-surface-card focus-visible:ring-accent-red/30",
        outline:
          "border border-hairline-strong bg-canvas text-ink hover:bg-surface-card",
        secondary:
          "border border-hairline-strong bg-surface-elevated text-ink hover:bg-surface-card",
        ghost: "text-body hover:bg-surface-elevated hover:text-ink",
        link: "text-link underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-sm px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 rounded-md px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-xs": "size-6 rounded-sm [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
