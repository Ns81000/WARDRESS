import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, RefreshCcw, ScanSearch, Settings2 } from "lucide-react"
import { Link, useParams } from "react-router"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
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
          <input
            type="checkbox"
            checked={autoScan}
            onChange={(e) => setAutoScan(e.target.checked)}
            className="size-4 accent-ink"
          />
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
  const queryClient = useQueryClient()

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
    queryKey: ["sites", siteId, "scans"],
    queryFn: () => apiClient.listScans(siteId!),
    enabled: !!siteId,
    refetchInterval: (query) =>
      query.state.data?.some(
        (s) => s.status === "pending" || s.status === "running"
      )
        ? 2000
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
  const scanInFlight = scans.data?.some(
    (x) => x.status === "pending" || x.status === "running"
  )

  return (
    <div>
      <Button asChild variant="ghost" size="sm" className="mb-6 -ml-2">
        <Link to="/">
          <ArrowLeft />
          Sites
        </Link>
      </Button>

      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-display-lg text-ink">{s.name}</h1>
          <p className="mt-2 text-code-md text-charcoal">{s.url}</p>
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

      <h2 className="mb-4 text-heading-md text-ink">Scans</h2>
      <div className="rounded-lg border border-hairline-strong bg-surface-card">
        {scans.isLoading ? (
          <p className="p-8 text-body-sm text-mute">Loading scans…</p>
        ) : scans.isError ? (
          <p className="p-8 text-body-sm text-accent-red">
            Could not load scans — is the API reachable?
          </p>
        ) : scans.data && scans.data.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Verdict</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Layers</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scans.data.map((scan) => (
                <TableRow key={scan.id}>
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
                        ? "Risk above the site threshold — review the evidence"
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
