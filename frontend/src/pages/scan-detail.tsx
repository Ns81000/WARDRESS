import { Suspense, lazy, useState, useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Download, FileText } from "lucide-react"
import { Link, useParams } from "react-router"
import { toast } from "sonner"

import { DomDiffTree } from "@/components/dom-diff-tree"
import { StatusDot } from "@/components/status-dot"
import { VisualDiffSlider } from "@/components/visual-diff-slider"
import { parseBboxValue, type Region } from "@/lib/bbox"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import * as apiClient from "@/lib/api"
import { ApiError } from "@/lib/api"
import type { ScanDetail, ScanVerdict } from "@/lib/api"
import {
  LAYER_TITLES,
  LAYER_BLURBS,
  scoreTone,
  dotFor,
  GenericEvidence,
  RENDERERS
} from "@/components/finding-card"
import { cn } from "@/lib/utils"

/*
 * Scan drilldown — the redesigned §5 evidence surface. Layout: identity header
 * inside a dashboard summary card with atmospheric glow, visual diff slider
 * and DOM diff tree inside a unified Workbench container (mock window with
 * traffic lights), and an interactive split Master-Detail dashboard for
 * inspectable detection layers.
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

/** Report export buttons — PDF (WeasyPrint) and Markdown, downloaded as
 * blobs so the Authorization header rides along. */
function ExportButtons({ scanId }: { scanId: string }) {
  const [busy, setBusy] = useState<"pdf" | "markdown" | null>(null)

  const download = async (format: "pdf" | "markdown") => {
    setBusy(format)
    try {
      const { url, filename } = await apiClient.downloadReport(scanId, format)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = filename
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Report export failed")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={busy !== null}
        onClick={() => void download("pdf")}
      >
        <Download className="mr-1.5 size-4" />
        {busy === "pdf" ? "Rendering PDF" : "PDF report"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={busy !== null}
        onClick={() => void download("markdown")}
      >
        <FileText className="mr-1.5 size-4" />
        {busy === "markdown" ? "Exporting" : "Markdown"}
      </Button>
    </div>
  )
}

function GeminiIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 296 298" xmlns="http://www.w3.org/2000/svg" fill="none">
      <mask id="a" width="296" height="298" x="0" y="0" maskUnits="userSpaceOnUse" style={{ maskType: "alpha" }}>
        <path fill="#3186FF" d="M141.201 4.886c2.282-6.17 11.042-6.071 13.184.148l5.985 17.37a184.004 184.004 0 0 0 111.257 113.049l19.304 6.997c6.143 2.227 6.156 10.91.02 13.155l-19.35 7.082a184.001 184.001 0 0 0-109.495 109.385l-7.573 20.629c-2.241 6.105-10.869 6.121-13.133.025l-7.908-21.296a184 184 0 0 0-109.02-108.658l-19.698-7.239c-6.102-2.243-6.118-10.867-.025-13.132l20.083-7.467A183.998 183.998 0 0 0 133.291 26.28l7.91-21.394Z" />
      </mask>
      <g mask="url(#a)">
        <g filter="url(#b)">
          <ellipse cx="163" cy="149" fill="#3689FF" rx="196" ry="159" />
        </g>
        <g filter="url(#c)">
          <ellipse cx="33.5" cy="142.5" fill="#F6C013" rx="68.5" ry="72.5" />
        </g>
        <g filter="url(#d)">
          <ellipse cx="19.5" cy="148.5" fill="#F6C013" rx="68.5" ry="72.5" />
        </g>
        <g filter="url(#e)">
          <path fill="#FA4340" d="M194 10.5C172 82.5 65.5 134.333 22.5 135L144-66l50 76.5Z" />
        </g>
        <g filter="url(#f)">
          <path fill="#FA4340" d="M190.5-12.5C168.5 59.5 62 111.333 19 112L140.5-89l50 76.5Z" />
        </g>
        <g filter="url(#g)">
          <path fill="#14BB69" d="M194.5 279.5C172.5 207.5 66 155.667 23 155l121.5 201 50-76.5Z" />
        </g>
        <g filter="url(#h)">
          <path fill="#14BB69" d="M196.5 320.5C174.5 248.5 68 196.667 25 196l121.5 201 50-76.5Z" />
        </g>
      </g>
      <defs>
        <filter id="b" width="464" height="390" x="-69" y="-46" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="18" />
        </filter>
        <filter id="c" width="265" height="273" x="-99" y="6" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
        </filter>
        <filter id="d" width="265" height="273" x="-113" y="12" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
        </filter>
        <filter id="e" width="299.5" height="329" x="-41.5" y="-130" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
        </filter>
        <filter id="f" width="299.5" height="329" x="-45" y="-153" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
        </filter>
        <filter id="g" width="299.5" height="329" x="-41" y="91" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
        </filter>
        <filter id="h" width="299.5" height="329" x="-39" y="132" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
        </filter>
      </defs>
    </svg>
  )
}

function ExplainCard({ siteId, scan }: { siteId: string; scan: ScanDetail }) {
  const queryClient = useQueryClient()
  const explain = useMutation({
    mutationFn: (force: boolean) => apiClient.explainScan(siteId, scan.id, force),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sites", siteId, "scans", scan.id] })
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Explanation unavailable")
    },
  })

  const text = explain.data?.explanation ?? scan.explanation
  const provider = explain.data?.provider ?? scan.explanation_provider
  const generatedAt = explain.data?.generated_at ?? scan.explanation_at

  return (
    <section className="mb-10">
      <div className="relative overflow-hidden rounded-lg border border-hairline-strong bg-surface-card p-6">
        <div className="absolute -top-16 -right-16 size-32 rounded-full bg-accent-orange/5 blur-2xl pointer-events-none" />
        
        {text ? (
          <div className="space-y-4">
            <div className="flex-items-center justify-between border-b border-hairline pb-3 flex">
              <div className="flex items-center gap-2">
                <GeminiIcon className="size-5 animate-pulse" />
                 <h3 className="text-body-sm font-medium text-ink">Incident explanation</h3>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={explain.isPending}
                onClick={() => explain.mutate(true)}
              >
                {explain.isPending ? "Analyzing..." : "Regenerate"}
              </Button>
            </div>
            
            <p className="text-body-md leading-relaxed text-body">{text}</p>
            
            <p className="text-caption text-mute pt-1">
               Generated by <span className="font-normal text-charcoal">{provider ?? "the configured provider"}</span>
              {generatedAt ? ` · ${new Date(generatedAt).toLocaleString()}` : ""} — an automated summary
              of the stored evidence, not a new scan.
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center text-center py-6 px-4">
            <div className="mb-4">
              <GeminiIcon className="size-14" />
            </div>
             <h3 className="text-body-sm font-medium text-ink mb-1.5">No incident explanation generated</h3>
            <p className="text-caption text-mute max-w-md mb-5 leading-relaxed">
              Ask our AI model to synthesize a plain-English explanation summarizing what changed on the site and how the risk score was calculated.
            </p>
            <Button
              variant="default"
              size="sm"
              disabled={explain.isPending}
              onClick={() => explain.mutate(false)}
               className="bg-primary hover:bg-surface-light text-primary-foreground font-medium"
            >
              <GeminiIcon className="mr-1.5 size-4" />
              {explain.isPending ? "Generating explanation..." : "Explain this incident"}
            </Button>
            <span className="mt-3 text-caption text-stone">
              Requires a Gemini key or Ollama configured in Settings.
            </span>
          </div>
        )}
      </div>
    </section>
  )
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

  const [activeLayerKey, setActiveLayerKey] = useState<string>("")

  // Set default active layer once scan data is loaded
  useEffect(() => {
    if (scan.data && !activeLayerKey) {
      const findings = scan.data.findings ?? []
      const flaggedOrChanged = findings.find((f) => !f.skipped && (f.score ?? 0) >= 0.15)
      const defaultKey = flaggedOrChanged?.layer_key ?? findings[0]?.layer_key ?? ""
      setActiveLayerKey(defaultKey)
    }
  }, [scan.data, activeLayerKey])

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
      <div className="mb-6 flex items-center justify-between">
        <Button asChild variant="ghost" size="sm" className="-ml-2 hover:bg-surface-elevated/40">
          <Link to={`/sites/${siteId}`} className="flex items-center gap-2 text-mute hover:text-ink">
            <ArrowLeft className="size-4" />
            <span className="font-display-sans text-button-sm">{site.data.name}</span>
          </Link>
        </Button>
      </div>

      <div className="relative mb-8 flex flex-col md:flex-row md:items-center justify-between gap-6 overflow-hidden rounded-lg border border-hairline-strong bg-surface-card p-6">
        {/* Ambient Glow behind header depending on severity */}
        <div className={cn(
          "absolute -top-24 -left-24 size-48 rounded-full blur-3xl pointer-events-none opacity-30",
          s.verdict === "flagged" && "bg-accent-red",
          s.verdict === "changed" && "bg-accent-orange",
          s.verdict === "clean" && "bg-accent-green"
        )} />
        
        <div className="z-10 min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-heading-md font-display text-ink sm:text-display-lg leading-tight">Scan report</h1>
            {verdictBadge(s.verdict, s.status)}
          </div>
          <p className="mt-2 text-body-md text-charcoal">{verdictLine(s, threshold)}</p>
          <p className="mt-1.5 text-caption text-mute">
            {s.started_at ? `Started ${new Date(s.started_at).toLocaleString()}` : ""}
            {s.finished_at ? ` · finished ${new Date(s.finished_at).toLocaleString()}` : ""}
          </p>
          {completed && (
            <div className="mt-4">
              <ExportButtons scanId={s.id} />
            </div>
          )}
        </div>

        {completed && s.risk_score != null && (
          <div className="z-10 flex shrink-0 justify-center md:justify-end">
            <div className="relative rounded-full p-2 bg-black/40 border border-hairline">
              <Suspense fallback={<div style={{ width: 148, height: 148 }} />}>
                <RiskGauge risk={s.risk_score} threshold={threshold} />
              </Suspense>
            </div>
          </div>
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

      {completed && siteId && <ExplainCard siteId={siteId} scan={s} />}

      {completed && (
        <div className="mb-10 grid grid-cols-1 gap-6 xl:grid-cols-2">
          {/* Visual comparison container */}
          <section className="flex flex-col overflow-hidden rounded-lg border border-hairline-strong bg-surface-card h-[680px]">
            {/* Header bar with traffic lights */}
            <div className="flex items-center justify-between border-b border-hairline bg-surface-elevated/40 px-4 py-3 shrink-0">
              <div className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-accent-red/80" />
                <span className="size-2.5 rounded-full bg-accent-yellow/80" />
                <span className="size-2.5 rounded-full bg-accent-green/80" />
              </div>
              <span className="font-mono text-code-md text-mute">visual-diff-slider</span>
              <div className="w-12" />
            </div>
            
            <div className="flex-1 p-5 flex flex-col min-h-0">
              <h3 className="mb-3 text-heading-sm font-display text-ink">Visual comparison</h3>
              {baselineShot && currentShot ? (
                <div className="flex-1 min-h-0 overflow-y-auto rounded-lg border border-hairline bg-surface-deep">
                  <VisualDiffSlider
                    baselinePath={baselineShot}
                    currentPath={currentShot}
                    suppressedRegions={suppressedRegions}
                  />
                </div>
              ) : (
                <div className="rounded-lg border border-hairline bg-surface-deep p-8 text-center flex-1 flex items-center justify-center">
                  <p className="text-body-sm text-mute">
                    Screenshots unavailable for this scan.
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* DOM changes container */}
          <section className="flex flex-col overflow-hidden rounded-lg border border-hairline-strong bg-surface-card h-[680px]">
            {/* Header bar with traffic lights */}
            <div className="flex items-center justify-between border-b border-hairline bg-surface-elevated/40 px-4 py-3 shrink-0">
              <div className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-accent-red/80" />
                <span className="size-2.5 rounded-full bg-accent-yellow/80" />
                <span className="size-2.5 rounded-full bg-accent-green/80" />
              </div>
              <span className="font-mono text-code-md text-mute">dom-diff-tree</span>
              <div className="w-12" />
            </div>
            
            <div className="flex-1 p-5 flex flex-col min-h-0">
              <h3 className="mb-3 text-heading-sm font-display text-ink">DOM changes</h3>
              {baselineHtml && currentHtml ? (
                <DomDiffTree
                  baselineHtmlPath={baselineHtml}
                  currentHtmlPath={currentHtml}
                  className="flex-1 min-h-0"
                />
              ) : (
                <div className="rounded-lg border border-hairline bg-surface-deep p-8 text-center flex-1 flex items-center justify-center">
                  <p className="text-body-sm text-mute">
                    HTML snapshots unavailable for this scan.
                  </p>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      <section className="mb-12">
        <h2 className="mb-4 text-heading-sm font-display text-ink">Detection layers</h2>
        {s.findings.length > 0 ? (
          <div className="flex flex-col lg:flex-row items-stretch gap-6 lg:h-[600px]">
            {/* Sidebar (Left Panel) */}
            <div className="w-full lg:w-5/12 xl:w-4/12 flex flex-col gap-2 shrink-0 lg:h-full lg:overflow-y-auto pr-1">
              {s.findings.map((finding) => {
                const isSelected = activeLayerKey === finding.layer_key
                const title = LAYER_TITLES[finding.layer_key] ?? finding.layer_key
                
                return (
                  <button
                    key={finding.layer_key}
                    type="button"
                    className={cn(
                      "w-full flex items-center justify-between gap-3 px-4 py-3 text-left rounded-lg border transition-all duration-150",
                      "hover:-translate-y-[1px] active:scale-[0.98]",
                       isSelected 
                         ? "border-accent-blue/80 bg-surface-elevated" 
                         : "border-hairline hover:border-hairline-strong bg-surface-card/60 hover:bg-surface-elevated/40"
                    )}
                    onClick={() => setActiveLayerKey(finding.layer_key)}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <StatusDot state={dotFor(finding)} />
                       <span className="rounded bg-surface-card px-1.5 py-0.5 text-caption font-mono text-mute border border-hairline-strong shrink-0">
                        L{finding.layer}
                      </span>
                      <span className={cn(
                        "text-body-sm font-medium truncate",
                         isSelected ? "text-ink" : "text-body"
                      )}>
                        {title}
                      </span>
                    </div>
                    <span className={cn("text-code-md font-mono font-medium shrink-0", scoreTone(finding.score))}>
                      {finding.skipped ? "skipped" : `${Math.round((finding.score ?? 0) * 100)}%`}
                    </span>
                  </button>
                )
              })}
            </div>

            {/* Detail Pane (Right Panel) */}
            <div className="flex-1 min-w-0 flex flex-col bg-surface-card border border-hairline-strong rounded-lg overflow-hidden lg:h-full">
              {(() => {
                const activeFinding = s.findings.find(f => f.layer_key === activeLayerKey)
                if (!activeFinding) {
                  return (
                    <div className="p-8 text-center text-body-sm text-mute">
                      Select a detection layer to inspect its findings.
                    </div>
                  )
                }
                
                const title = LAYER_TITLES[activeFinding.layer_key] ?? activeFinding.layer_key
                const blurb = LAYER_BLURBS[activeFinding.layer_key]
                const Renderer = RENDERERS[activeFinding.layer_key]
                const evidence = activeFinding.evidence ?? {}

                return (
                  <div 
                    key={activeFinding.layer_key} // Triggers re-mounting and runs the blur animation
                    className="flex flex-col h-full animate-detail-in"
                  >
                    {/* Header bar */}
                    <div className="px-6 py-4 border-b border-hairline bg-surface-elevated/20 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-caption text-mute font-mono">L{activeFinding.layer}</span>
                          <h3 className="text-heading-sm font-display text-ink">{title}</h3>
                        </div>
                        {blurb && (
                          <p className="mt-1 text-caption text-mute leading-relaxed">{blurb}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className={cn(
                          "rounded-full px-3 py-1 text-code-md font-semibold border",
                          activeFinding.skipped 
                            ? "bg-stone/10 border-stone/30 text-stone"
                            : (activeFinding.score ?? 0) >= 0.5
                              ? "bg-accent-red/10 border-accent-red/30 text-accent-red"
                              : (activeFinding.score ?? 0) >= 0.15
                                ? "bg-accent-orange/10 border-accent-orange/30 text-accent-orange"
                                : "bg-accent-green/10 border-accent-green/30 text-accent-green"
                        )}>
                          {activeFinding.skipped ? "Skipped" : `${Math.round((activeFinding.score ?? 0) * 100)}% Risk`}
                        </span>
                      </div>
                    </div>

                    {/* Scrollable Content Area */}
                    <div className="p-6 flex-1 overflow-y-auto bg-grid-pattern">
                      {activeFinding.skipped ? (
                        <div className="rounded-lg bg-surface-deep p-6 border border-hairline">
                          <h4 className="text-body-sm font-medium text-ink mb-2">Layer Skipped</h4>
                          <p className="text-body-sm text-mute leading-relaxed">
                            {String(evidence.reason ?? "Layer did not run for this scan.")}
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {Renderer ? (
                            <Renderer e={evidence} />
                          ) : (
                            <GenericEvidence evidence={evidence} />
                          )}
                          
                          {evidence.suppression_applied != null && (
                            <div className="mt-6 rounded-lg bg-accent-orange/5 border border-accent-orange/20 p-4">
                              <p className="text-caption text-accent-orange leading-relaxed">
                                Suppression rules were applied to this comparison — excluded content did not contribute to the score.
                              </p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-hairline-strong bg-surface-card p-8 text-center">
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
