import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronLeft, ChevronRight, Inbox } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import * as apiClient from "@/lib/api"
import { ApiError, type Alert, type AlertDelivery } from "@/lib/api"
import { cn } from "@/lib/utils"

/*
 * Alerts feed — one row per flagged scan, with per-channel delivery
 * outcomes expanded inline. Failed deliveries are first-class content
 * here: a broken channel must be visible, not buried in worker logs.
 */

const PAGE_SIZE = 25

function getAlertChannelIcon(key: string, className?: string) {
  const classStr = cn("size-4.5 shrink-0", className)
  switch (key) {
    case "ntfy":
      return (
        <svg className={classStr} fill="#317F6F" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <title>ntfy</title>
          <path d="M12.597 13.693v2.156h6.205v-2.156ZM5.183 6.549v2.363l3.591 1.901.023.01-.023.009-3.591 1.901v2.35l.386-.211 5.456-2.969V9.729ZM3.659 2.037C1.915 2.037.42 3.41.42 5.154v.002L.438 18.73 0 21.963l5.956-1.583h14.806c1.744 0 3.238-1.374 3.238-3.118V5.154c0-1.744-1.493-3.116-3.237-3.117h-.001zm0 2.2h17.104c.613.001 1.037.447 1.037.917v12.108c0 .47-.424.916-1.038.916H5.633l-3.026.915.031-.179-.017-13.76c0-.47.424-.917 1.038-.917z" />
        </svg>
      )
    case "slack":
      return (
        <svg className={classStr} viewBox="0 0 2447.6 2452.5" xmlns="http://www.w3.org/2000/svg">
          <g clipRule="evenodd" fillRule="evenodd">
            <path d="m897.4 0c-135.3.1-244.8 109.9-244.7 245.2-.1 135.3 109.5 245.1 244.8 245.2h244.8v-245.1c.1-135.3-109.5-245.1-244.9-245.3.1 0 .1 0 0 0m0 654h-652.6c-135.3.1-244.9 109.9-244.8 245.2-.2 135.3 109.4 245.1 244.7 245.3h652.7c135.3-.1 244.9-109.9 244.8-245.2.1-135.4-109.5-245.2-244.8-245.3z" fill="#36c5f0" />
            <path d="m2447.6 899.2c.1-135.3-109.5-245.1-244.8-245.2-135.3.1-244.9 109.9-244.8 245.2v245.3h244.8c135.3-.1 244.9-109.9 244.8-245.3zm-652.7 0v-654c.1-135.2-109.4-245-244.7-245.2-135.3.1-244.9 109.9-244.8 245.2v654c-.2 135.3 109.4 245.1 244.7 245.3 135.3-.1 244.9-109.9 244.8-245.3z" fill="#2eb67d" />
            <path d="m1550.1 2452.5c135.3-.1 244.9-109.9 244.8-245.2.1-135.3-109.5-245.1-244.8-245.2h-244.8v245.2c-.1 135.2 109.5 245 244.8 245.2zm0-654.1h652.7c135.3-.1 244.9-109.9 244.8-245.2.2-135.3-109.4-245.1-244.7-245.3h-652.7c-135.3.1-244.9 109.9-244.8 245.2-.1 135.4 109.4 245.2 244.7 245.3z" fill="#ecb22e" />
            <path d="m0 1553.2c-.1 135.3 109.5 245.1 244.8 245.2 135.3-.1 244.9-109.9 244.8-245.2v-245.2h-244.8c-135.3.1-244.9 109.9-244.8 245.2zm652.7 0v654c-.2 135.3 109.4 245.1 244.7 245.3 135.3-.1 244.9-109.9 244.8-245.2v-653.9c.2-135.3-109.4-245.1-244.7-245.3-135.4 0-244.9 109.8-244.8 245.1 0 0 0 .1 0 0" fill="#e01e5a" />
          </g>
        </svg>
      )
    case "discord":
      return (
        <svg className={classStr} viewBox="0 0 256 199" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid">
          <path d="M216.856 16.597A208.502 208.502 0 0 0 164.042 0c-2.275 4.113-4.933 9.645-6.766 14.046-19.692-2.961-39.203-2.961-58.533 0-1.832-4.4-4.55-9.933-6.846-14.046a207.809 207.809 0 0 0-52.855 16.638C5.618 67.147-3.443 116.4 1.087 164.956c22.169 16.555 43.653 26.612 64.775 33.193A161.094 161.094 0 0 0 79.735 175.3a136.413 136.413 0 0 1-21.846-10.632 108.636 108.636 0 0 0 5.356-4.237c42.122 19.702 87.89 19.702 129.51 0a131.66 131.66 0 0 0 5.355 4.237 136.07 136.07 0 0 1-21.886 10.653c4.006 8.02 8.638 15.67 13.873 22.848 21.142-6.58 42.646-16.637 64.815-33.213 5.316-56.288-9.08-105.09-38.056-148.36ZM85.474 135.095c-12.645 0-23.015-11.805-23.015-26.18s10.149-26.2 23.015-26.2c12.867 0 23.236 11.804 23.015 26.2.02 14.375-10.148 26.18-23.015 26.18Zm85.051 0c-12.645 0-23.014-11.805-23.014-26.18s10.148-26.2 23.014-26.2c12.867 0 23.236 11.804 23.015 26.2 0 14.375-10.148 26.18-23.015 26.18Z" fill="#5865F2" />
        </svg>
      )
    case "webhook":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 239" id="webhooks">
          <path fill="#C73A63" d="M119.54 100.503c-10.61 17.836-20.775 35.108-31.152 52.25-2.665 4.401-3.984 7.986-1.855 13.58 5.878 15.454-2.414 30.493-17.998 34.575-14.697 3.851-29.016-5.808-31.932-21.543-2.584-13.927 8.224-27.58 23.58-29.757 1.286-.184 2.6-.205 4.762-.367l23.358-39.168C73.612 95.465 64.868 78.39 66.803 57.23c1.368-14.957 7.25-27.883 18-38.477 20.59-20.288 52.002-23.573 76.246-8.001 23.284 14.958 33.948 44.094 24.858 69.031-6.854-1.858-13.756-3.732-21.343-5.79 2.854-13.865.743-26.315-8.608-36.981-6.178-7.042-14.106-10.733-23.12-12.093-18.072-2.73-35.815 8.88-41.08 26.618-5.976 20.13 3.069 36.575 27.784 48.967z" />
          <path fill="#4B4B4B" d="M149.841 79.41c7.475 13.187 15.065 26.573 22.587 39.836 38.02-11.763 66.686 9.284 76.97 31.817 12.422 27.219 3.93 59.457-20.465 76.25-25.04 17.238-56.707 14.293-78.892-7.851 5.654-4.733 11.336-9.487 17.407-14.566 21.912 14.192 41.077 13.524 55.305-3.282 12.133-14.337 11.87-35.714-.615-49.75-14.408-16.197-33.707-16.691-57.035-1.143-9.677-17.168-19.522-34.199-28.893-51.491-3.16-5.828-6.648-9.21-13.77-10.443-11.893-2.062-19.571-12.275-20.032-23.717-.453-11.316 6.214-21.545 16.634-25.53 10.322-3.949 22.435-.762 29.378 8.014 5.674 7.17 7.477 15.24 4.491 24.083-.83 2.466-1.905 4.852-3.07 7.774z" />
          <path fill="#4A4A4A" d="M167.707 187.21h-45.77c-4.387 18.044-13.863 32.612-30.19 41.876-12.693 7.2-26.373 9.641-40.933 7.29-26.808-4.323-48.728-28.456-50.658-55.63-2.184-30.784 18.975-58.147 47.178-64.293 1.947 7.071 3.915 14.21 5.862 21.264-25.876 13.202-34.832 29.836-27.59 50.636 6.375 18.304 24.484 28.337 44.147 24.457 20.08-3.962 30.204-20.65 28.968-47.432 19.036 0 38.088-.197 57.126.097 7.434.117 13.173-.654 18.773-7.208 9.22-10.784 26.191-9.811 36.121.374 10.148 10.409 9.662 27.157-1.077 37.127-10.361 9.62-26.73 9.106-36.424-1.26-1.992-2.136-3.562-4.673-5.533-7.298z" />
        </svg>
      )
    case "email":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" viewBox="0 49.4 512 399.42">
          <g fill="none" fillRule="evenodd">
            <g fillRule="nonzero">
              <path fill="#4285f4" d="M34.91 448.818h81.454V251L0 163.727V413.91c0 19.287 15.622 34.91 34.91 34.91z" />
              <path fill="#34a853" d="M395.636 448.818h81.455c19.287 0 34.909-15.622 34.909-34.909V163.727L395.636 251z" />
              <path fill="#fbbc04" d="M395.636 99.727V251L512 163.727v-46.545c0-43.142-49.25-67.782-83.782-41.891z" />
            </g>
            <path fill="#ea4335" d="M116.364 251V99.727L256 204.455 395.636 99.727V251L256 355.727z" />
            <path fill="#c5221f" fillRule="nonzero" d="M0 117.182v46.545L116.364 251V99.727L83.782 75.291C49.25 49.4 0 74.04 0 117.18z" />
          </g>
        </svg>
      )
    case "telegram":
      return (
        <svg className={classStr} viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid">
          <defs>
            <linearGradient id="tg-a" x1="50%" x2="50%" y1="0%" y2="100%">
              <stop offset="0%" stopColor="#2AABEE" />
              <stop offset="100%" stopColor="#229ED9" />
            </linearGradient>
          </defs>
          <path fill="url(#tg-a)" d="M128 0C94.06 0 61.48 13.494 37.5 37.49A128.038 128.038 0 0 0 0 128c0 33.934 13.5 66.514 37.5 90.51C61.48 242.506 94.06 256 128 256s66.52-13.494 90.5-37.49c24-23.996 37.5-56.576 37.5-90.51 0-33.934-13.5-66.514-37.5-90.51C194.52 13.494 161.94 0 128 0Z" />
          <path fill="#FFF" d="M57.94 126.648c37.32-16.256 62.2-26.974 74.64-32.152 35.56-14.786 42.94-17.354 47.76-17.441 1.06-.017 3.42.245 4.96 1.49 1.28 1.05 1.64 2.47 1.82 3.467.16.996.38 3.266.2 5.038-1.92 20.24-10.26 69.356-14.5 92.026-1.78 9.592-5.32 12.808-8.74 13.122-7.44.684-13.08-4.912-20.28-9.63-11.26-7.386-17.62-11.982-28.56-19.188-12.64-8.328-4.44-12.906 2.76-20.386 1.88-1.958 34.64-31.748 35.26-34.45.08-.338.16-1.598-.6-2.262-.74-.666-1.84-.438-2.64-.258-1.14.256-19.12 12.152-54 35.686-5.1 3.508-9.72 5.218-13.88 5.128-4.56-.098-13.36-2.584-19.9-4.708-8-2.606-14.38-3.984-13.82-8.41.28-2.304 3.46-4.662 9.52-7.072Z" />
        </svg>
      )
    default:
      return (
        <svg className={classStr} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      )
  }
}

function getAlertIconKey(type: string, name: string): string {
  const t = type.toLowerCase()
  const n = name.toLowerCase()
  if (t === "email") return "email"
  if (t === "telegram") return "telegram"
  if (t === "discord" || n.includes("discord")) return "discord"
  if (t === "slack" || n.includes("slack")) return "slack"
  if (t === "ntfy" || n.includes("ntfy")) return "ntfy"
  if (t === "webhook" || n.includes("webhook") || n.includes("json")) return "webhook"
  return "other"
}

function deliveryDot(d: AlertDelivery): DotState {
  switch (d.status) {
    case "sent":
      return "clean"
    case "failed":
      return "threat"
    case "skipped":
      return "idle"
    default:
      return "pending"
  }
}

function deliveryBadge(d: AlertDelivery) {
  switch (d.status) {
    case "sent":
      return <Badge variant="clean" className="font-mono text-xs">sent</Badge>
    case "failed":
      return <Badge variant="threat" className="font-mono text-xs">failed</Badge>
    case "skipped":
      return <Badge variant="secondary" className="font-mono text-xs">skipped</Badge>
    default:
      return <Badge variant="pending" className="font-mono text-xs">pending</Badge>
  }
}

function AlertRow({ alert }: { alert: Alert }) {
  const queryClient = useQueryClient()
  const [showDeliveries, setShowDeliveries] = useState(false)
  const ack = useMutation({
    mutationFn: () => apiClient.ackAlert(alert.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["alerts"] })
      toast.success("Alert acknowledged")
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not acknowledge"),
  })

  const riskPct = alert.risk_score != null ? `${Math.round(alert.risk_score * 100)}%` : "—"
  const failed = alert.deliveries.filter((d) => d.status === "failed").length

  return (
    <li className={cn(
      "relative overflow-hidden rounded-lg border bg-surface-card p-3.5 transition-all duration-150 border-hairline-strong mb-2.5",
      alert.acknowledged_at 
        ? "border-l-4 border-l-stone/30 bg-surface-card/60" 
        : "border-l-4 border-l-accent-red bg-surface-card hover:bg-surface-elevated/20"
    )}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Left main info */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 min-w-0">
          <div className="flex items-center gap-2.5">
            <StatusDot state={alert.acknowledged_at ? "idle" : "threat"} />
            <Link
              to={`/sites/${alert.site_id}/scans/${alert.scan_id}`}
              className="truncate text-body-sm font-medium text-ink hover:underline"
            >
              {alert.site_name ?? "Unknown site"}
            </Link>
            <span className="h-[22px] inline-flex items-center font-mono text-xs font-bold text-accent-red bg-accent-red/5 px-1.5 rounded border border-accent-red/20 leading-none">{riskPct}</span>
          </div>

          <span className="text-caption text-mute">
            Flagged {new Date(alert.created_at).toLocaleDateString()} at {new Date(alert.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>

          <span className="h-[22px] inline-flex items-center font-mono text-xs text-charcoal bg-surface-deep px-1.5 rounded border border-hairline select-none leading-none">
            {alert.id.slice(0, 8)}
          </span>

          {alert.deliveries.length > 0 && (
            <button
              type="button"
              onClick={() => setShowDeliveries(d => !d)}
              className={cn(
                "h-[22px] inline-flex items-center gap-1.5 text-[11px] font-semibold hover:text-ink select-none rounded px-2 border transition-all cursor-pointer leading-none",
                failed > 0 
                  ? "bg-accent-red/10 text-accent-red border-accent-red/30 hover:bg-accent-red/20" 
                  : "bg-surface-deep text-mute border-hairline hover:bg-surface-elevated"
              )}
            >
              Deliveries ({alert.deliveries.length})
              {failed > 0 && <span className="size-1 rounded-full bg-accent-red animate-pulse" />}
            </button>
          )}
        </div>

        {/* Right Action button */}
        {!alert.acknowledged_at && (
          <Button 
            variant="outline" 
            size="sm" 
            disabled={ack.isPending} 
            onClick={() => ack.mutate()}
            className="h-8 hover:-translate-y-[1px] active:scale-[0.97] transition-all px-2.5 text-caption"
          >
            <Check className="mr-1.5 size-3.5 shrink-0" />
            Acknowledge
          </Button>
        )}
      </div>

      {/* Expanded detailed delivery logs */}
      {showDeliveries && alert.deliveries.length > 0 && (
        <div className="mt-3.5 rounded border border-hairline bg-surface-deep/20 p-3 space-y-2">
          <div className="flex items-center justify-between border-b border-hairline pb-1.5 select-none">
            <span className="text-caption font-mono uppercase tracking-wider text-mute">
              Delivery Channels Log
            </span>
            {failed > 0 && (
              <span className="text-caption text-accent-red font-semibold">
                {failed} Channel Error{failed === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <ul className="space-y-1.5 font-mono text-code-md">
            {alert.deliveries.map((d) => (
              <li key={d.id} className="flex flex-wrap items-start justify-between gap-3 p-1.5 bg-surface-card/45 border border-hairline rounded hover:bg-surface-elevated/20 transition-colors">
                <div className="flex items-center gap-2">
                  <StatusDot state={deliveryDot(d)} />
                  {getAlertChannelIcon(getAlertIconKey(d.channel_type, d.channel_name), "size-4.5")}
                  <span className="font-semibold text-ink text-xs">{d.channel_name}</span>
                  <span className="text-mute text-[10px]">({d.channel_type})</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {deliveryBadge(d)}
                </div>
                {d.detail && (
                  <div className={cn(
                    "w-full text-caption border-t border-hairline-strong/60 pt-1 mt-1 font-sans leading-relaxed pl-1",
                    d.status === "failed" ? "text-accent-red/90 font-medium" : "text-mute"
                  )}>
                    {d.detail}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      
      {alert.deliveries.length === 0 && (
        <div className="mt-3 rounded border border-dashed border-hairline p-3 text-caption text-mute bg-surface-deep/15">
          No notification channels were configured when this alert fired. You can configure them in Settings.
        </div>
      )}
    </li>
  )
}

export function AlertsPage() {
  const [page, setPage] = useState(0)
  const [unackedOnly, setUnackedOnly] = useState(false)

  const alerts = useQuery({
    queryKey: ["alerts", { page, unackedOnly }],
    queryFn: () => apiClient.listAlerts(page * PAGE_SIZE, PAGE_SIZE, unackedOnly),
    refetchInterval: 30000,
  })

  const total = alerts.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="max-w-5xl mx-auto py-4">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-hairline pb-6">
        <div>
          <h1 className="text-display-lg text-ink font-display">Alerts</h1>
          <p className="mt-2 text-body-md text-charcoal">
            Every flagged scan, with where (and whether) its notifications landed.
          </p>
        </div>
        <label className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-hairline-strong bg-surface-card hover:bg-surface-elevated/40 cursor-pointer select-none text-body-sm text-charcoal transition-all">
          <input
            type="checkbox"
            checked={unackedOnly}
            onChange={(e) => {
              setUnackedOnly(e.target.checked)
              setPage(0)
            }}
            className="size-3.5 accent-primary cursor-pointer rounded"
          />
          <span className="font-medium text-ink">Unacknowledged only</span>
        </label>
      </div>

      <div>
        {alerts.isLoading ? (
          <div className="rounded-lg border border-hairline-strong bg-surface-card p-12 text-center">
            <p className="text-body-sm text-mute">Loading alerts…</p>
          </div>
        ) : alerts.isError ? (
          <div className="rounded-lg border border-hairline-strong bg-surface-card p-12 text-center">
            <p className="text-body-sm text-accent-red font-medium">
              Could not load alerts — is the API reachable?
            </p>
          </div>
        ) : (alerts.data?.items.length ?? 0) > 0 ? (
          <ul className="space-y-2">
            {alerts.data!.items.map((a) => (
              <AlertRow key={a.id} alert={a} />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center gap-3 p-16 text-center border border-dashed border-hairline-strong rounded-lg bg-surface-card/40">
            <div className="rounded-full bg-surface-deep border border-hairline p-4 mb-2">
              <Inbox className="size-8 text-mute/50" />
            </div>
            <p className="text-heading-sm font-semibold text-ink">
              {unackedOnly ? "All caught up" : "No alerts"}
            </p>
            <p className="max-w-md text-body-sm text-charcoal leading-relaxed">
              {unackedOnly 
                ? "All flagged incidents have been acknowledged. Your workspace is currently clean."
                : "Alerts appear when a scan's fused risk score crosses your site's flag threshold."}
            </p>
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="mt-6 flex items-center justify-end gap-2 border-t border-hairline pt-4">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Newer alerts"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="hover:bg-surface-elevated"
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="text-caption text-mute font-medium px-2">
            {page + 1} / {pageCount}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Older alerts"
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            className="hover:bg-surface-elevated"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
