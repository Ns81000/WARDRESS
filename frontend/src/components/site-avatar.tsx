import { cn } from "@/lib/utils"
import { siteAvatarFor } from "@/lib/site-avatar"

/*
 * Local, deterministic stand-in for the third-party favicon service this
 * component replaces: rendering a monitored site's hostname into a remote
 * <img> URL disclosed the operator's full watchlist (including internal
 * hostnames) to that service on every dashboard view. This avatar is
 * generated entirely client-side — no network request, air-gap safe.
 */

export function SiteAvatar({ url, className }: { url: string; className?: string }) {
  const { initial, tone } = siteAvatarFor(url)
  return (
    <span
      aria-hidden="true"
      title={url}
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded border border-hairline font-semibold",
        tone,
        className || "size-4.5 text-[9px]",
      )}
    >
      {initial}
    </span>
  )
}
