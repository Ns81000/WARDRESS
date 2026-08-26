import { useEffect, useState } from "react"

import { fetchSiteIconObjectURL } from "@/lib/api"
import type { SiteIconState } from "@/lib/site-icon-state"

/**
 * Fetch the opt-in site icon as an authenticated blob. 404/network error/
 * still-loading all report "fallback" so the caller renders SiteAvatar —
 * no flash of a broken image, no layout shift (the box is reserved by the
 * component in both states). StrictMode's double-mounted effect is safe:
 * each mount owns its fetch, stale responses are discarded, and every
 * object URL is revoked exactly once (on replacement or unmount).
 */
export function useSiteIcon(siteId: string): SiteIconState {
  const [state, setState] = useState<SiteIconState>({ phase: "loading" })

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null

    setState({ phase: "loading" })
    fetchSiteIconObjectURL(siteId)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        objectUrl = url
        setState({ phase: "ok", url })
      })
      .catch(() => {
        if (!cancelled) setState({ phase: "fallback" })
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [siteId])

  return state
}
