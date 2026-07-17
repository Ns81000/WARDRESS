import { Suspense, lazy } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"
import { Link, useParams } from "react-router"

import { DomDiffTree } from "@/components/dom-diff-tree"
import { FindingCard } from "@/components/finding-card"
import { StatusDot } from "@/components/status-dot"
import { VisualDiffSlider } from "@/components/visual-diff-slider"
import { parseBboxValue, type Region } from "@/lib/bbox"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import * as apiClient from "@/lib/api"
import type { ScanDetail, ScanVerdict } from "@/lib/api"

/*
 * Scan drilldown — the §5 evidence surface. Layout: identity header
 * (verdict, risk gauge, timing), then the visual diff slider and DOM
 * diff tree side by side (§4 components), then every layer's finding
 * card in §5 order.
 */

const RiskGauge = lazy(() =>
  import("@/components/risk-gauge").then((m) => ({ default: m.RiskGauge }))
)

function verdictBadge(verdict: ScanVerdict, status: string) {
  if (status === "failed" || verdict === "error") return <Badge variant="pending">Error</Badge>
  if (verdict === "clean") return <Badge variant="clean">Clean</Badge>
  if (verdict === "changed") return <Badge variant="pending">Changed</Badge>
  if (verdict === "flagged") return <Badge variant="threat">Flagged</Badge>
  return <Badge variant="secondary">{status}</Badge>
}

function verdictLine(scan: ScanDetail, threshold: number): string {
  if (scan.error) return scan.error
  const pct = Math.round((scan.risk_score ?? 0) * 100)
  const thresholdPct = Math.round(threshold * 100)
  if (scan.verdict === "flagged")
    return `Fused risk ${pct}% is at or above this site's ${thresholdPct}% flag threshold — review the per-layer evidence below.`
  if (scan.verdict === "changed")
    return `Changes were detected, but fused risk ${pct}% stays below the ${thresholdPct}% flag threshold.`
  if (scan.verdict === "clean") return "No change detected against the baseline."
  return "Scan has not completed."
}

export function ScanDetailPage() {
  const { siteId, scanId } = useParams<{ siteId: string; scanId: string }>()

  const site = useQuery({
    queryKey: ["sites", siteId],
    queryFn: () => apiClient.getSite(siteId!),
    enabled: !!siteId,
  })
  const scan = useQuery({
    queryKey: ["sites", siteId, "scans", scanId],
    queryFn: () => apiClient.getScan(siteId!, scanId!),
    enabled: !!siteId && !!scanId,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === "pending" || s === "running" ? 2000 : false
    },
  })
  const rules = useQuery({
    queryKey: ["sites", siteId, "suppression-rules"],
    queryFn: () => apiClient.listSuppressionRules(siteId!),
    enabled: !!siteId,
  })

  if (site.isLoading || scan.isLoading) {
    return <p className="text-body-sm text-mute">Loading scan…</p>
  }
  if (site.isError || scan.isError || !site.data || !scan.data) {
    return (
      <div>
        <p className="text-body-sm text-accent-red">Scan not found.</p>
        <Button asChild variant="link" className="mt-2 px-0">
          <Link to={siteId ? `/sites/${siteId}` : "/"}>Back to site</Link>
        </Button>
      </div>
    )
  }

  const s = scan.data
  const threshold = site.data.flag_threshold
  const completed = s.status === "completed"
  const inFlight = s.status === "pending" || s.status === "running"
  const suppressedRegions: Region[] = (rules.data ?? [])
    .filter((r) => r.type === "bbox")
    .map((r) => parseBboxValue(r.value))
    .filter((r): r is Region => r !== null)

  // Screenshots: baseline side comes from the scan's own baseline row so
  // the comparison matches what the engine actually diffed. Artifact
  // endpoints 404 when a capture is missing; the viewers degrade to an
  // "unavailable" note.
  const baselineShot = s.baseline_id
    ? apiClient.baselineScreenshotPath(s.baseline_id)
    : null
  const currentShot = apiClient.scanScreenshotPath(s.id)
  const baselineHtml = s.baseline_id ? apiClient.baselineHtmlPath(s.baseline_id) : null
  const currentHtml = apiClient.scanHtmlPath(s.id)

  return (
    <div>
      <Button asChild variant="ghost" size="sm" className="mb-6 -ml-2">
        <Link to={`/sites/${siteId}`}>
          <ArrowLeft />
          {site.data.name}
        </Link>
      </Button>

      <div className="mb-8 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-display-lg text-ink">Scan report</h1>
            {verdictBadge(s.verdict, s.status)}
          </div>
          <p className="mt-2 text-body-sm text-charcoal">{verdictLine(s, threshold)}</p>
          <p className="mt-1 text-caption text-mute">
            {s.started_at ? `Started ${new Date(s.started_at).toLocaleString()}` : ""}
            {s.finished_at ? ` · finished ${new Date(s.finished_at).toLocaleString()}` : ""}
          </p>
        </div>
        {completed && s.risk_score != null && (
          <Suspense fallback={<div style={{ width: 148, height: 148 }} />}>
            <RiskGauge risk={s.risk_score} threshold={threshold} />
          </Suspense>
        )}
      </div>

      {inFlight && (
        <div className="mb-8 flex items-center gap-2 rounded-lg border border-hairline-strong bg-surface-card px-5 py-4">
          <StatusDot state="pending" />
          <span className="text-body-sm text-body">
            {s.status === "pending" ? "Queued — waiting for a worker" : "Scan running now"}
          </span>
        </div>
      )}

      {completed && (
        <div className="mb-10 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <section>
            <h2 className="mb-3 text-heading-sm text-ink">Visual comparison</h2>
            {baselineShot && currentShot ? (
              <VisualDiffSlider
                baselinePath={baselineShot}
                currentPath={currentShot}
                suppressedRegions={suppressedRegions}
              />
            ) : (
              <div className="rounded-lg border border-hairline-strong bg-surface-card p-8">
                <p className="text-body-sm text-mute">
                  Screenshots unavailable for this scan.
                </p>
              </div>
            )}
          </section>
          <section>
            <h2 className="mb-3 text-heading-sm text-ink">DOM changes</h2>
            {baselineHtml && currentHtml ? (
              <DomDiffTree
                baselineHtmlPath={baselineHtml}
                currentHtmlPath={currentHtml}
              />
            ) : (
              <div className="rounded-lg border border-hairline-strong bg-surface-card p-8">
                <p className="text-body-sm text-mute">
                  HTML snapshots unavailable for this scan.
                </p>
              </div>
            )}
          </section>
        </div>
      )}

      <section>
        <h2 className="mb-3 text-heading-sm text-ink">Detection layers</h2>
        {s.findings.length > 0 ? (
          <div className="space-y-2">
            {s.findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-hairline-strong bg-surface-card p-8">
            <p className="text-body-sm text-mute">
              {inFlight
                ? "Findings appear when the scan completes."
                : "No per-layer findings were stored for this scan."}
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
