import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import * as apiClient from "@/lib/api"
import { ApiError } from "@/lib/api"

/*
 * Opt-in site favicon resolver (Settings). OFF by default: sites pages
 * render local letter tiles and nothing leaves the deployment. ON: this
 * server fetches each monitored site's favicon once and caches it
 * locally — the toggle is the operator's explicit consent to that single
 * outbound request per site.
 */
export function FaviconCard() {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ["settings", "favicon"],
    queryFn: apiClient.getFaviconSettings,
  })

  const save = useMutation({
    mutationFn: (enabled: boolean) => apiClient.putFaviconSettings(enabled),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "favicon"] })
      toast.success(
        data.enabled
          ? "Site favicons enabled — each monitored site is fetched once and cached locally"
          : "Site favicons disabled — sites pages stay fully local",
      )
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not save the setting"),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Site favicons
          <Badge variant={settings.data?.enabled ? "clean" : "secondary"}>
            {settings.data?.enabled ? "On" : "Off"}
          </Badge>
        </CardTitle>
        <CardDescription>
          Off (default): sites pages show local letter tiles — nothing leaves your deployment.
          On: your server fetches each monitored site&rsquo;s favicon once and caches it locally.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={settings.data?.enabled ?? false}
          aria-label="Enable site favicons"
          disabled={!settings.data || save.isPending}
          data-testid="favicon-toggle"
          onClick={() => save.mutate(!settings.data?.enabled)}
          className={`relative h-6 w-11 shrink-0 cursor-pointer rounded-full border transition-colors disabled:opacity-50 ${
            settings.data?.enabled
              ? "border-accent-green/60 bg-accent-green/30"
              : "border-hairline-strong bg-surface-elevated"
          }`}
        >
          <span
            className={`absolute top-0.5 size-4.5 rounded-full bg-surface-card border border-hairline-strong transition-all ${
              settings.data?.enabled ? "left-[22px]" : "left-0.5"
            }`}
          />
        </button>
        <span className="text-body-sm text-body">
          {settings.isLoading ? "Loading…" : settings.data?.enabled ? "Favicons on" : "Favicons off"}
        </span>
      </CardContent>
    </Card>
  )
}
