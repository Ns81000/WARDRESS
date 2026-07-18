import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Crosshair, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { bboxValue, parseBboxValue, type Region } from "@/lib/bbox"
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
import * as apiClient from "@/lib/api"
import { ApiError, type SuppressionRule, type SuppressionRuleType } from "@/lib/api"
import { useArtifact } from "@/lib/use-artifact"
import { cn } from "@/lib/utils"

/*
 * False-positive suppression (§5) — a real point-and-click UI feature:
 * - draw an ignore region directly on the site's screenshot (bbox rule)
 * - add CSS-selector exclusions for DOM subtrees
 * - add regex exclusions for dynamic text
 * Rules apply from the next scan onward; the engine records what it
 * suppressed in each scan's evidence.
 */

const TYPE_LABELS: Record<SuppressionRuleType, string> = {
  css_selector: "CSS selector",
  regex: "Regex",
  bbox: "Region",
}

function describeRule(rule: SuppressionRule): string {
  if (rule.type === "bbox") {
    const r = parseBboxValue(rule.value)
    if (!r) return rule.value
    return `${Math.round(r.w * 100)}×${Math.round(r.h * 100)}% at ${Math.round(r.x * 100)},${Math.round(r.y * 100)}%`
  }
  return rule.value
}

/** Screenshot with existing ignore regions overlaid and drag-to-draw. */
function RegionPicker({
  screenshotPath,
  existing,
  onDrawn,
}: {
  screenshotPath: string
  existing: Region[]
  onDrawn: (region: Region) => void
}) {
  const shot = useArtifact(screenshotPath)
  const [draft, setDraft] = useState<Region | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const start = useRef<{ x: number; y: number } | null>(null)

  const point = (e: React.PointerEvent) => {
    // Measure against the inner content div (full image height), not the
    // scrollable wrapper: its rect moves with scroll, so fractions stay
    // anchored to the image even when the user has scrolled down.
    const rect = contentRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || rect.height === 0) return { x: 0, y: 0 }
    return {
      x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    }
  }

  if (shot.loading)
    return <p className="p-4 text-body-sm text-mute">Loading screenshot…</p>
  if (shot.error || !shot.url)
    return (
      <p className="p-4 text-body-sm text-mute">
        Screenshot unavailable — capture a baseline first.
      </p>
    )

  return (
    <div>
      <p className="mb-2 text-caption text-charcoal">
        Drag a rectangle over the area to ignore (ads, counters, rotating
        content). Colored areas are already ignored.
      </p>
      <div
        className="relative max-h-[420px] touch-none overflow-y-auto rounded-lg border border-hairline-strong select-none"
        style={{
          cursor: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='5' fill='%23ffffff'/%3E%3Ccircle cx='8' cy='8' r='3' fill='%23171717'/%3E%3C/svg%3E") 8 8, cell`
        }}
        onPointerDown={(e) => {
          e.preventDefault()
          start.current = point(e)
          setDraft(null)
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={(e) => {
          if (!start.current) return
          const p = point(e)
          const s = start.current
          setDraft({
            x: Math.min(s.x, p.x),
            y: Math.min(s.y, p.y),
            w: Math.abs(p.x - s.x),
            h: Math.abs(p.y - s.y),
          })
        }}
        onPointerUp={(e) => {
          if (start.current && draft && draft.w > 0.005 && draft.h > 0.005)
            onDrawn(draft)
          start.current = null
          setDraft(null)
          e.currentTarget.releasePointerCapture?.(e.pointerId)
        }}
      >
        <div ref={contentRef} className="relative">
          <img src={shot.url} alt="Baseline capture" className="block w-full" draggable={false} />
          {existing.map((r, i) => (
            <div
              key={i}
              aria-hidden
              className="pointer-events-none absolute rounded-xs"
              style={{
                left: `${r.x * 100}%`,
                top: `${r.y * 100}%`,
                width: `${r.w * 100}%`,
                height: `${r.h * 100}%`,
                border: "1.5px solid rgba(245, 158, 11, 0.95)",
                outline: "1px solid rgba(255, 255, 255, 0.85)",
                backgroundColor: "rgba(245, 158, 11, 0.12)",
                backgroundImage:
                  "repeating-linear-gradient(45deg, rgba(245, 158, 11, 0.15) 0 4px, transparent 4px 8px)",
              }}
            />
          ))}
          {draft && (
            <div
              aria-hidden
              className="pointer-events-none absolute rounded-xs"
              style={{
                left: `${draft.x * 100}%`,
                top: `${draft.y * 100}%`,
                width: `${draft.w * 100}%`,
                height: `${draft.h * 100}%`,
                border: "1.5px dashed rgba(59, 130, 246, 0.95)",
                outline: "1px solid rgba(255, 255, 255, 0.85)",
                backgroundColor: "rgba(59, 130, 246, 0.08)",
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

export function SuppressionPanel({
  siteId,
  baselineScreenshotPath,
}: {
  siteId: string
  /** Screenshot the region picker draws on (current baseline); null
   * while no baseline exists — bbox drawing is hidden then. */
  baselineScreenshotPath: string | null
}) {
  const queryClient = useQueryClient()
  const [drawOpen, setDrawOpen] = useState(false)
  const [selector, setSelector] = useState("")
  const [regex, setRegex] = useState("")

  const rules = useQuery({
    queryKey: ["sites", siteId, "suppression-rules"],
    queryFn: () => apiClient.listSuppressionRules(siteId),
  })

  const createMutation = useMutation({
    mutationFn: (payload: { type: SuppressionRuleType; value: string; note?: string }) =>
      apiClient.createSuppressionRule(siteId, payload),
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["sites", siteId, "suppression-rules"],
      })
      toast.success(
        variables.type === "bbox"
          ? "Region will be ignored from the next scan"
          : "Exclusion added — applies from the next scan"
      )
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not save the rule")
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (ruleId: string) => apiClient.deleteSuppressionRule(siteId, ruleId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["sites", siteId, "suppression-rules"],
      })
      toast.success("Rule removed")
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not remove the rule")
    },
  })

  const bboxRegions = (rules.data ?? [])
    .filter((r) => r.type === "bbox")
    .map((r) => parseBboxValue(r.value))
    .filter((r): r is Region => r !== null)

  const addSelector = () => {
    const v = selector.trim()
    if (!v) return
    createMutation.mutate(
      { type: "css_selector", value: v },
      { onSuccess: () => setSelector("") }
    )
  }
  const addRegex = () => {
    const v = regex.trim()
    if (!v) return
    createMutation.mutate({ type: "regex", value: v }, { onSuccess: () => setRegex("") })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Suppression rules</CardTitle>
        <CardDescription>
          Exclude known-dynamic content from change detection — ignored
          regions, selectors, and text patterns never contribute to a
          scan&apos;s risk score.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Existing rules */}
        {rules.isLoading ? (
          <p className="text-body-sm text-mute">Loading rules…</p>
        ) : rules.isError ? (
          <p className="text-body-sm text-accent-red">Could not load suppression rules.</p>
        ) : rules.data && rules.data.length > 0 ? (
          <ul className="space-y-2">
            {rules.data.map((rule) => (
              <li
                key={rule.id}
                className="flex items-center gap-3 rounded-md border border-hairline bg-surface-deep px-3 py-2"
              >
                <Badge variant="outline">{TYPE_LABELS[rule.type]}</Badge>
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate",
                    rule.type === "bbox" ? "text-body-sm text-body" : "text-code-md text-body"
                  )}
                  title={rule.value}
                >
                  {describeRule(rule)}
                </span>
                {rule.note && (
                  <span className="hidden truncate text-caption text-mute sm:inline">
                    {rule.note}
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Delete rule"
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(rule.id)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-sm text-mute">
            No rules yet. Suppression is how recurring false positives get
            silenced without loosening detection.
          </p>
        )}

        {/* Region picker */}
        {baselineScreenshotPath && (
          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDrawOpen((o) => !o)}
              aria-expanded={drawOpen}
            >
              <Crosshair />
              {drawOpen ? "Close region picker" : "Ignore a screenshot region"}
            </Button>
            {drawOpen && (
              <div className="mt-3">
                <RegionPicker
                  screenshotPath={baselineScreenshotPath}
                  existing={bboxRegions}
                  onDrawn={(region) =>
                    createMutation.mutate({ type: "bbox", value: bboxValue(region) })
                  }
                />
              </div>
            )}
          </div>
        )}

        {/* Selector / regex forms */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="supp-selector">Ignore a CSS selector</Label>
            <div className="flex gap-2">
              <Input
                id="supp-selector"
                placeholder="#visitor-counter, .ad-slot"
                value={selector}
                onChange={(e) => setSelector(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addSelector()}
                className="font-mono text-code-md"
              />
              <Button
                variant="secondary"
                size="icon-sm"
                aria-label="Add selector rule"
                disabled={!selector.trim() || createMutation.isPending}
                onClick={addSelector}
              >
                <Plus />
              </Button>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="supp-regex">Ignore a text pattern (regex)</Label>
            <div className="flex gap-2">
              <Input
                id="supp-regex"
                placeholder="Session id: \w+"
                value={regex}
                onChange={(e) => setRegex(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addRegex()}
                className="font-mono text-code-md"
              />
              <Button
                variant="secondary"
                size="icon-sm"
                aria-label="Add regex rule"
                disabled={!regex.trim() || createMutation.isPending}
                onClick={addRegex}
              >
                <Plus />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
