import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronLeft, ChevronRight } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import * as apiClient from "@/lib/api"
import { ApiError, type Alert, type AlertDelivery } from "@/lib/api"

/*
 * Alerts feed — one row per flagged scan, with per-channel delivery
 * outcomes expanded inline. Failed deliveries are first-class content
 * here: a broken channel must be visible, not buried in worker logs.
 */

const PAGE_SIZE = 25

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
      return <Badge variant="clean">Sent</Badge>
    case "failed":
      return <Badge variant="threat">Failed</Badge>
    case "skipped":
      return <Badge variant="secondary">Skipped</Badge>
    default:
      return <Badge variant="pending">Pending</Badge>
  }
}

function AlertRow({ alert }: { alert: Alert }) {
  const queryClient = useQueryClient()
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
    <li className="border-b border-hairline p-5 last:border-b-0">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <StatusDot state={alert.acknowledged_at ? "idle" : "threat"} />
            <Link
              to={`/sites/${alert.site_id}/scans/${alert.scan_id}`}
              className="truncate text-heading-sm text-ink hover:underline"
            >
              {alert.site_name ?? "Unknown site"}
            </Link>
            <span className="text-code-md text-accent-red">{riskPct}</span>
            {failed > 0 && (
              <Badge variant="threat">
                {failed} delivery {failed === 1 ? "failure" : "failures"}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-caption text-mute">
            Flagged {new Date(alert.created_at).toLocaleString()}
            {alert.acknowledged_at &&
              ` · acknowledged via ${alert.acknowledged_via ?? "dashboard"} ${new Date(
                alert.acknowledged_at
              ).toLocaleString()}`}
            {" · alert "}
            <span className="text-code-md">{alert.id.slice(0, 8)}</span>
          </p>
        </div>
        {!alert.acknowledged_at && (
          <Button variant="outline" size="sm" disabled={ack.isPending} onClick={() => ack.mutate()}>
            <Check />
            Acknowledge
          </Button>
        )}
      </div>

      {alert.deliveries.length > 0 && (
        <ul className="mt-4 space-y-2 border-l border-hairline pl-4">
          {alert.deliveries.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-3">
              <StatusDot state={deliveryDot(d)} />
              <span className="text-body-sm text-body">{d.channel_name}</span>
              <span className="text-caption text-mute">{d.channel_type}</span>
              {deliveryBadge(d)}
              {d.detail && <span className="text-body-sm text-charcoal">{d.detail}</span>}
            </li>
          ))}
        </ul>
      )}
      {alert.deliveries.length === 0 && (
        <p className="mt-3 text-caption text-mute">
          No notification channels were configured when this alert fired.
        </p>
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
    <div>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-lg text-ink">Alerts</h1>
          <p className="mt-2 text-body-md text-charcoal">
            Every flagged scan, with where (and whether) its notifications
            landed.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-body-sm text-charcoal">
          <input
            type="checkbox"
            checked={unackedOnly}
            onChange={(e) => {
              setUnackedOnly(e.target.checked)
              setPage(0)
            }}
            className="size-4 accent-ink"
          />
          Unacknowledged only
        </label>
      </div>

      <div className="rounded-lg border border-hairline-strong bg-surface-card">
        {alerts.isLoading ? (
          <p className="p-8 text-body-sm text-mute">Loading alerts…</p>
        ) : alerts.isError ? (
          <p className="p-8 text-body-sm text-accent-red">
            Could not load alerts — is the API reachable?
          </p>
        ) : (alerts.data?.items.length ?? 0) > 0 ? (
          <ul>
            {alerts.data!.items.map((a) => (
              <AlertRow key={a.id} alert={a} />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center gap-3 p-16 text-center">
            <p className="text-heading-sm text-ink">
              {unackedOnly ? "Nothing awaiting acknowledgement" : "No alerts"}
            </p>
            <p className="max-w-sm text-body-sm text-charcoal">
              Alerts appear when a scan&rsquo;s fused risk crosses a site&rsquo;s flag
              threshold.
            </p>
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Newer alerts"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft />
          </Button>
          <span className="text-caption text-mute">
            {page + 1} / {pageCount}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Older alerts"
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            <ChevronRight />
          </Button>
        </div>
      )}
    </div>
  )
}
