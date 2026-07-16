import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, RefreshCcw, ScanSearch } from "lucide-react"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import * as apiClient from "@/lib/api"
import { ApiError, type Scan } from "@/lib/api"

function verdictBadge(scan: Scan) {
  if (scan.status === "failed" || scan.verdict === "error")
    return <Badge variant="pending">Error</Badge>
  if (scan.status === "pending" || scan.status === "running")
    return <Badge variant="secondary">{scan.status === "pending" ? "Queued" : "Running"}</Badge>
  if (scan.verdict === "clean") return <Badge variant="clean">Clean</Badge>
  if (scan.verdict === "changed") return <Badge variant="threat">Changed</Badge>
  return <Badge variant="secondary">Unknown</Badge>
}

function scanDot(scan: Scan): DotState {
  if (scan.status === "pending" || scan.status === "running") return "pending"
  if (scan.status === "failed" || scan.verdict === "error") return "pending"
  if (scan.verdict === "changed") return "threat"
  if (scan.verdict === "clean") return "clean"
  return "idle"
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

        <Card>
          <CardHeader>
            <CardTitle>Monitoring</CardTitle>
            <CardDescription>
              Phase 1 checks the content hash (layer 1). The full nine-layer
              engine arrives with scheduled scans.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={s.allow_private_networks ? "pending" : "clean"} />
              {s.allow_private_networks
                ? "Private-network target allowed (explicit opt-in)"
                : "Public targets only (SSRF guard active)"}
            </div>
          </CardContent>
        </Card>
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
                <TableHead>Content hash</TableHead>
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
                  <TableCell className="text-code-md text-charcoal">
                    {scan.content_hash ? `${scan.content_hash.slice(0, 16)}…` : "—"}
                  </TableCell>
                  <TableCell className="text-body-sm text-mute">
                    {scan.started_at
                      ? new Date(scan.started_at).toLocaleString()
                      : new Date(scan.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="max-w-md truncate text-body-sm text-charcoal">
                    {scan.error
                      ? scan.error
                      : scan.verdict === "changed"
                        ? "Content hash differs from baseline"
                        : scan.verdict === "clean"
                          ? "Content identical to baseline"
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
