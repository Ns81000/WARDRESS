import { Suspense, lazy, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  RefreshCcw,
  ScanSearch,
  Settings2,
} from "lucide-react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"

import { RemediationHooksPanel } from "@/components/remediation-hooks-panel"
import { StatusDot, type DotState } from "@/components/status-dot"
import { SuppressionPanel } from "@/components/suppression-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import * as apiClient from "@/lib/api"
import { ApiError, type Scan, type Site } from "@/lib/api"

const IncidentTimeline = lazy(() =>
  import("@/components/incident-timeline").then((m) => ({
    default: m.IncidentTimeline,
  }))
)

const SCANS_PAGE_SIZE = 20
// The timeline reads a deeper slice than the table page so history is
// visible at a glance; pagination covers the rest.
const TIMELINE_WINDOW = 200

function verdictBadge(scan: Scan) {
  if (scan.status === "failed" || scan.verdict === "error")
    return <Badge variant="pending">Error</Badge>
  if (scan.status === "pending" || scan.status === "running")
    return <Badge variant="secondary">{scan.status === "pending" ? "Queued" : "Running"}</Badge>
  if (scan.verdict === "clean") return <Badge variant="clean">Clean</Badge>
  if (scan.verdict === "changed") return <Badge variant="pending">Changed</Badge>
  if (scan.verdict === "flagged") return <Badge variant="threat">Flagged</Badge>
  return <Badge variant="secondary">Unknown</Badge>
}

function scanDot(scan: Scan): DotState {
  if (scan.status === "pending" || scan.status === "running") return "pending"
  if (scan.status === "failed" || scan.verdict === "error") return "pending"
  if (scan.verdict === "flagged") return "threat"
  if (scan.verdict === "changed") return "pending"
  if (scan.verdict === "clean") return "clean"
  return "idle"
}

function riskCell(scan: Scan) {
  if (scan.risk_score == null) return <span className="text-mute">—</span>
  const pct = Math.round(scan.risk_score * 100)
  const tone =
    scan.verdict === "flagged"
      ? "text-accent-red"
      : scan.verdict === "changed"
        ? "text-accent-orange"
        : "text-accent-green"
  return <span className={`text-code-md ${tone}`}>{pct}%</span>
}

function layerSummary(scan: Scan): string {
  if (!scan.layer_scores) return "—"
  const entries = Object.entries(scan.layer_scores).filter(
    ([k]) => k !== "layer9_fusion"
  )
  const ran = entries.filter(([, v]) => !v.skipped)
  const hits = ran.filter(([, v]) => (v.score ?? 0) > 0.05).length
  return `${ran.length}/${entries.length} layers ran · ${hits} signaled`
}

function SettingsCard({ site }: { site: Site }) {
  const queryClient = useQueryClient()
  const [threshold, setThreshold] = useState(String(Math.round(site.flag_threshold * 100)))
  const [interval, setInterval] = useState(String(site.scan_interval_minutes))
  const [autoScan, setAutoScan] = useState(site.auto_scan_enabled)

  const muted =
    site.muted_until != null && new Date(site.muted_until).getTime() > Date.now()

  const mutation = useMutation({
    mutationFn: (patch: apiClient.SiteSettingsPatch) =>
      apiClient.updateSite(site.id, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sites", site.id] })
      toast.success("Monitoring settings saved")
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not save settings")
    },
  })

  const muteMutation = useMutation({
    mutationFn: (minutes: number) =>
      apiClient.updateSite(site.id, { mute_minutes: minutes }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ["sites", site.id] })
      toast.success(
        updated.muted_until
          ? `Alerts muted until ${new Date(updated.muted_until).toLocaleString()}`
          : "Alerts unmuted"
      )
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not change mute state")
    },
  })

  const save = () => {
    const t = Number(threshold)
    const i = Number(interval)
    if (!Number.isFinite(t) || t < 0 || t > 100) {
      toast.error("Flag threshold must be between 0 and 100%")
      return
    }
    if (!Number.isFinite(i) || i < 5 || i > 1440) {
      toast.error("Scan interval must be between 5 and 1440 minutes")
      return
    }
    mutation.mutate({
      flag_threshold: t / 100,
      scan_interval_minutes: Math.round(i),
      auto_scan_enabled: autoScan,
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Monitoring</CardTitle>
        <CardDescription>
          Scans run automatically on an adaptive cadence: faster right after
          a change, relaxing back while stable.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 text-body-sm text-body">
          <StatusDot state={site.allow_private_networks ? "pending" : "clean"} />
          {site.allow_private_networks
            ? "Private-network target allowed (explicit opt-in)"
            : "Public targets only (SSRF guard active)"}
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="flag-threshold">Flag threshold (%)</Label>
            <Input
              id="flag-threshold"
              inputMode="numeric"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="scan-interval">Base interval (min)</Label>
            <Input
              id="scan-interval"
              inputMode="numeric"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
            />
          </div>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-body-sm text-body">
          <span className="flex min-h-11 min-w-11 items-center justify-center md:min-h-0 md:min-w-0">
            <input
              type="checkbox"
              checked={autoScan}
              onChange={(e) => setAutoScan(e.target.checked)}
              className="size-4 accent-ink"
            />
          </span>
          Scheduled scans enabled
        </label>
        {site.next_scan_at && site.auto_scan_enabled && (
          <p className="text-caption text-mute">
            Next scheduled scan {new Date(site.next_scan_at).toLocaleString()}
            {site.current_interval_minutes
              ? ` · current cadence ${site.current_interval_minutes} min`
              : ""}
          </p>
        )}
        <div className="flex items-center justify-between border-t border-hairline pt-4">
          <div className="flex items-center gap-2 text-body-sm text-body">
            <StatusDot state={muted ? "pending" : "clean"} />
            {muted
              ? `Alerts muted until ${new Date(site.muted_until!).toLocaleString()}`
              : "Alert delivery active"}
          </div>
          <div className="flex items-center gap-1">
            {muted ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={muteMutation.isPending}
                onClick={() => muteMutation.mutate(0)}
              >
                Unmute
              </Button>
            ) : (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={muteMutation.isPending}
                  onClick={() => muteMutation.mutate(60)}
                >
                  Mute 1h
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={muteMutation.isPending}
                  onClick={() => muteMutation.mutate(24 * 60)}
                >
                  24h
                </Button>
              </>
            )}
          </div>
        </div>
        {muted && (
          <p className="text-caption text-mute">
            Scans keep running while muted; skipped deliveries stay visible on
            the Alerts page.
          </p>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={mutation.isPending}
          onClick={save}
        >
          <Settings2 />
          Save settings
        </Button>
      </CardContent>
    </Card>
  )
}

export function SiteDetailPage() {
  const { siteId } = useParams<{ siteId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)

  const site = useQuery({
    queryKey: ["sites", siteId],
    queryFn: () => apiClient.getSite(siteId!),
    enabled: !!siteId,
    refetchInterval: (query) => {
      const s = query.state.data?.baseline_status
      return s === "pending" || s === "capturing" ? 3000 : false
    },
  })

  const scans = useQuery({
    queryKey: ["sites", siteId, "scans", { page }],
    queryFn: () => apiClient.listScans(siteId!, page * SCANS_PAGE_SIZE, SCANS_PAGE_SIZE),
    enabled: !!siteId,
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (s) => s.status === "pending" || s.status === "running"
      )
        ? 2000
        : false,
  })

  // Timeline slice: deeper than one table page, refreshed with the list.
  const history = useQuery({
    queryKey: ["sites", siteId, "scans", "timeline"],
    queryFn: () => apiClient.listScans(siteId!, 0, TIMELINE_WINDOW),
    enabled: !!siteId,
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (s) => s.status === "pending" || s.status === "running"
      )
        ? 5000
        : false,
  })

  const scanMutation = useMutation({
    mutationFn: () => apiClient.scanNow(siteId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sites", siteId, "scans"] })
      toast.success("Scan queued")
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not start scan")
    },
  })

  const rebaselineMutation = useMutation({
    mutationFn: () => apiClient.rebaseline(siteId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sites", siteId] })
      toast.success("Baseline capture queued")
    },
    onError: (err) => {
      toast.error(
        err instanceof ApiError ? err.message : "Could not start capture"
      )
    },
  })

  if (site.isLoading) {
    return <p className="text-body-sm text-mute">Loading…</p>
  }
  if (site.isError || !site.data) {
    return (
      <div>
        <p className="text-body-sm text-accent-red">Site not found.</p>
        <Button asChild variant="link" className="mt-2 px-0">
          <Link to="/">Back to sites</Link>
        </Button>
      </div>
    )
  }

  const s = site.data
  const baselineReady = s.baseline_status === "ready"
  const scanInFlight = scans.data?.items.some(
    (x) => x.status === "pending" || x.status === "running"
  )
  const totalScans = scans.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(totalScans / SCANS_PAGE_SIZE))

  return (
    <div>
      <Button asChild variant="ghost" size="sm" className="mb-6 -ml-2">
        <Link to="/">
          <ArrowLeft />
          Sites
        </Link>
      </Button>

      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-display-lg text-ink">{s.name}</h1>
          <p className="mt-2 truncate text-code-md text-charcoal">{s.url}</p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            disabled={
              rebaselineMutation.isPending ||
              s.baseline_status === "pending" ||
              s.baseline_status === "capturing"
            }
            onClick={() => rebaselineMutation.mutate()}
          >
            <RefreshCcw />
            Rebaseline
          </Button>
          <Button
            disabled={!baselineReady || scanInFlight || scanMutation.isPending}
            onClick={() => scanMutation.mutate()}
          >
            <ScanSearch />
            Scan now
          </Button>
        </div>
      </div>

      <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Baseline</CardTitle>
            <CardDescription>
              The trusted capture every scan is compared against.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <StatusDot
                state={
                  baselineReady
                    ? "clean"
                    : s.baseline_status === "failed"
                      ? "threat"
                      : "pending"
                }
              />
              <span className="text-body-sm text-body">
                {s.baseline_status === "ready" && "Ready"}
                {s.baseline_status === "pending" && "Queued for capture"}
                {s.baseline_status === "capturing" && "Capturing now"}
                {s.baseline_status === "failed" && "Capture failed"}
                {!s.baseline_status && "None"}
              </span>
            </div>
            {s.baseline_captured_at && (
              <p className="mt-2 text-caption text-mute">
                Captured {new Date(s.baseline_captured_at).toLocaleString()}
              </p>
            )}
            {s.baseline_error && (
              <p className="mt-2 text-body-sm text-accent-red">
                {s.baseline_error}
              </p>
            )}
          </CardContent>
        </Card>

        <SettingsCard key={s.id + String(s.flag_threshold)} site={s} />
      </div>

      <h2 className="mb-4 text-heading-md text-ink">Risk history</h2>
      <div className="mb-8">
        <Suspense
          fallback={
            <div className="flex h-[220px] items-center justify-center rounded-lg border border-hairline-strong bg-surface-card">
              <p className="text-body-sm text-mute">Loading timeline…</p>
            </div>
          }
        >
          <IncidentTimeline
            scans={history.data?.items ?? []}
            threshold={s.flag_threshold}
            onPointClick={(scanId) => void navigate(`/sites/${s.id}/scans/${scanId}`)}
          />
        </Suspense>
      </div>

      <div className="mb-8">
        <SuppressionPanel
          siteId={s.id}
          baselineScreenshotPath={
            baselineReady && s.baseline_id
              ? apiClient.baselineScreenshotPath(s.baseline_id)
              : null
          }
        />
      </div>

      <div className="mb-8">
        <RemediationHooksPanel siteId={s.id} />
      </div>

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-heading-md text-ink">Scans</h2>
        {pageCount > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Newer scans"
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
              aria-label="Older scans"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              <ChevronRight />
            </Button>
          </div>
        )}
      </div>
      <div className="rounded-lg border border-hairline-strong bg-surface-card">
        {scans.isLoading ? (
          <p className="p-8 text-body-sm text-mute">Loading scans…</p>
        ) : scans.isError ? (
          <p className="p-8 text-body-sm text-accent-red">
            Could not load scans — is the API reachable?
          </p>
        ) : scans.data && scans.data.items.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Verdict</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Layers</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Summary</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scans.data.items.map((scan) => (
                <TableRow
                  key={scan.id}
                  className="cursor-pointer"
                  onClick={() => void navigate(`/sites/${s.id}/scans/${scan.id}`)}
                >
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <StatusDot state={scanDot(scan)} />
                      <span className="text-body-sm capitalize">{scan.status}</span>
                    </span>
                  </TableCell>
                  <TableCell>{verdictBadge(scan)}</TableCell>
                  <TableCell>{riskCell(scan)}</TableCell>
                  <TableCell className="text-caption text-mute">
                    {layerSummary(scan)}
                  </TableCell>
                  <TableCell className="text-body-sm text-mute">
                    {scan.started_at
                      ? new Date(scan.started_at).toLocaleString()
                      : new Date(scan.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="max-w-md truncate text-body-sm text-charcoal">
                    {scan.error
                      ? scan.error
                      : scan.verdict === "flagged"
                        ? "Risk above the site threshold — open for evidence"
                        : scan.verdict === "changed"
                          ? "Changes detected below the flag threshold"
                          : scan.verdict === "clean"
                            ? "No change against baseline"
                            : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="p-8 text-body-sm text-charcoal">
            No scans yet.{" "}
            {baselineReady
              ? "Run the first scan with the button above."
              : "Waiting for the baseline capture to finish."}
          </p>
        )}
      </div>
    </div>
  )
}
