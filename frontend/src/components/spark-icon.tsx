import fabricIcon from "@/assets/fabric-iq.svg"
import { cn } from "@/lib/utils"

/*
 * The product's own AI mark (assets/fabric-iq.svg, bundled same-origin).
 * Replaces the generic lucide Sparkles glyph at every AI-sparkle call site
 * so the brand mark is consistent everywhere intelligence is invoked.
 * Rendered as a plain <img> — never inlined SVG markup (an XSS vector)
 * and never a remote URL.
 */
export function SparkIcon({ className }: { className?: string }) {
  return (
    <img
      src={fabricIcon}
      alt=""
      aria-hidden="true"
      className={cn("shrink-0 object-contain", className)}
    />
  )
}
