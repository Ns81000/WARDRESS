import { useQuery } from "@tanstack/react-query"
import { Activity, Database, HardDrive, Timer } from "lucide-react"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import * as apiClient from "@/lib/api"

/*
 * Operational health (Phase 5, §7/§11) — queue depth, scan latency, DB
 * size, component liveness, uptime. Every metric degrades gracefully:
 * the page's whole purpose is to render when something is down.
 */

function componentDot(status: string): DotState {
  if (status === "ok") return "clean"
  if (status === "down") return "threat"
  if (status === "degraded") return "pending"
  return "pending"
}

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${seconds % 60}s`
}

function fmtBytes(bytes: number | null): string {
  if (bytes == null) return "n/a"
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${Math.round(bytes / 1024)} KB`
}

function fmtAgo(iso: string | null): string {
  if (!iso) return "never"
  const ms = Date.now() - new Date(iso).getTime()
  const min = Math.floor(ms / 60000)
  if (min < 1) return "just now"
  if (min < 60) return `${min}m ago`
  const h = Math.floor(min / 60)
  return h < 48 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`
}

function Stat({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode
  label: string
  value: string
  hint?: string
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-5">
        <div className="mt-1 text-charcoal">{icon}</div>
        <div>
          <p className="text-caption uppercase tracking-wide text-mute">{label}</p>
          <p className="mt-1 text-heading-md text-ink">{value}</p>
          {hint && <p className="mt-0.5 text-caption text-mute">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

const COMPONENT_LABELS: Record<string, string> = {
  database: "PostgreSQL",
  redis: "Redis broker",
  worker: "Scan worker",
}

export function HealthPage() {
  const health = useQuery({
    queryKey: ["health-details"],
    queryFn: apiClient.getHealthDetails,
    refetchInterval: 15000,
  })

  const h = health.data

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-display-lg text-ink">System health</h1>
          <p className="mt-2 text-body-md text-charcoal">
            The watcher, watched — queue, workers, database, and scan
            throughput at a glance.
          </p>
        </div>
        {h && (
          <Badge
            variant={h.status === "ok" ? "clean" : h.status === "degraded" ? "pending" : "threat"}
          >
            {h.status === "ok" ? "All systems normal" : h.status}
          </Badge>
        )}
      </div>

      {health.isLoading ? (
        <p className="text-body-sm text-mute">Reading system status…</p>
      ) : health.isError ? (
        <p className="text-body-sm text-accent-red">
          Could not read system status — the API itself may be unhealthy.
        </p>
      ) : h ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              icon={<Timer className="size-4" />}
              label="API uptime"
              value={fmtUptime(h.uptime_seconds)}
            />
            <Stat
              icon={<Activity className="size-4" />}
              label="Queue depth"
              value={h.queue_depth != null ? String(h.queue_depth) : "n/a"}
              hint="tasks waiting for a worker"
            />
            <Stat
              icon={<HardDrive className="size-4" />}
              label="Database size"
              value={fmtBytes(h.db_size_bytes)}
            />
            <Stat
              icon={<Database className="size-4" />}
              label="Scans (24h)"
              value={String(h.scans_last_24h)}
              hint={
                h.avg_scan_seconds != null
                  ? `avg ${h.avg_scan_seconds.toFixed(1)}s per scan`
                  : undefined
              }
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Components</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="divide-y divide-hairline">
                {Object.entries(h.components).map(([key, comp]) => (
                  <li key={key} className="flex items-center gap-3 py-3">
                    <StatusDot state={componentDot(comp.status)} />
                    <span className="text-body-sm text-body">
                      {COMPONENT_LABELS[key] ?? key}
                    </span>
                    <span className="text-caption text-mute">{comp.status}</span>
                    {comp.detail && (
                      <span className="ml-auto text-caption text-charcoal">{comp.detail}</span>
                    )}
                  </li>
                ))}
                <li className="flex items-center gap-3 py-3">
                  <StatusDot
                    state={
                      h.last_dispatch_tick_at &&
                      Date.now() - new Date(h.last_dispatch_tick_at).getTime() < 5 * 60_000
                        ? "clean"
                        : "pending"
                    }
                  />
                  <span className="text-body-sm text-body">Beat scheduler</span>
                  <span className="ml-auto text-caption text-charcoal">
                    last dispatch tick {fmtAgo(h.last_dispatch_tick_at)}
                  </span>
                </li>
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Monitoring activity</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-1 gap-4 text-body-sm sm:grid-cols-3">
                <div>
                  <dt className="text-caption uppercase tracking-wide text-mute">
                    Sites monitored
                  </dt>
                  <dd className="mt-1 text-body">{h.sites_total}</dd>
                </div>
                <div>
                  <dt className="text-caption uppercase tracking-wide text-mute">
                    Last completed scan
                  </dt>
                  <dd className="mt-1 text-body">{fmtAgo(h.last_scan_at)}</dd>
                </div>
                <div>
                  <dt className="text-caption uppercase tracking-wide text-mute">
                    Liveness endpoint
                  </dt>
                  <dd className="mt-1 text-code-md text-body">GET /api/health/live</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  )
}
