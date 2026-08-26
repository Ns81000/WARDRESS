import { useSiteIcon } from "@/lib/use-site-icon"
import { SiteAvatar } from "@/components/site-avatar"
import { cn } from "@/lib/utils"
/*
 * The site's identity mark: its real favicon when the opt-in server-side
 * resolver has cached one, otherwise the local letter avatar (also shown
 * while loading and whenever the resolver is off or the fetch fails).
 * Both states reserve the SAME box — no layout shift when the icon pops
 * in. The avatar remains the default-off UI; nothing here ever talks to a
 * third-party image host.
 */
export function SiteFavicon({
  siteId,
  url,
  className,
}: {
  siteId: string
  url: string
  className?: string
}) {
  const state = useSiteIcon(siteId)

  if (state.phase === "ok") {
    return (
      <img
        src={state.url}
        alt=""
        aria-hidden="true"
        className={cn(
          "shrink-0 rounded object-contain border border-hairline bg-surface-card",
          className || "size-4.5",
        )}
      />
    )
  }

  return <SiteAvatar url={url} className={className} />
}
