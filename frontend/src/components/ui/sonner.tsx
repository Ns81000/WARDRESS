import type * as React from "react"
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

/*
 * Wardress reskin — toasts render on surface-elevated with hairline
 * borders and 12px radius. Theme is pinned dark: the entire product
 * lives on the true-black canvas (no next-themes, no light mode).
 */
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4 text-accent-green" />,
        info: <InfoIcon className="size-4 text-accent-blue" />,
        warning: <TriangleAlertIcon className="size-4 text-accent-orange" />,
        error: <OctagonXIcon className="size-4 text-accent-red" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--color-surface-elevated)",
          "--normal-text": "var(--color-ink)",
          "--normal-border": "var(--color-hairline-strong)",
          "--border-radius": "var(--radius-lg)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
