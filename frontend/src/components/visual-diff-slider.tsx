import { useCallback, useEffect, useRef, useState } from "react"

import { ChevronLeft, ChevronRight } from "lucide-react"

import type { Region } from "@/lib/bbox"
import { useArtifact } from "@/lib/use-artifact"
import { cn } from "@/lib/utils"

/*
 * Visual diff slider — §4 Wardress-specific component:
 * baseline/current full-page screenshots overlaid with a draggable
 * divider (baseline left of the divider, current right), altered-pixel
 * regions highlighted with a translucent accent-red overlay. The design
 * doc's rule is explicit: never a solid neon fill — the overlay is
 * rgba(255,32,71,~0.28) with a hairline accent border.
 *
 * Region detection runs client-side: both images are downsampled onto
 * canvases and compared in coarse blocks; contiguous changed blocks are
 * merged into rectangles. This is presentation-layer highlighting — the
 * authoritative visual score is layer 4's SSIM/pHash evidence.
 */

const BLOCK = 24 // compare-grid cell size (downsampled px)
const DIFF_THRESHOLD = 26 // mean abs luma delta 0-255 for a "changed" block
const COMPARE_WIDTH = 480

function luma(d: Uint8ClampedArray, i: number): number {
  return 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
}

/** Downsample an image to the compare width (preserving aspect) and
 * return pixel data for its top `height` rows. Drawing at the image's
 * own scaled height and reading only the top slice crops — squashing
 * the whole page into the slice would misalign the two sides whenever
 * their heights differ. */
function samplePixels(
  img: HTMLImageElement,
  width: number,
  height: number
): Uint8ClampedArray | null {
  const scaledH = Math.max(
    height,
    Math.round(img.naturalHeight * (width / img.naturalWidth))
  )
  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  if (!ctx) return null
  ctx.drawImage(img, 0, 0, width, scaledH)
  return ctx.getImageData(0, 0, width, height).data
}

/** Merge adjacent changed blocks into rectangles (greedy row-major). */
function mergeBlocks(changed: boolean[][], cols: number, rows: number): Region[] {
  const used = changed.map((row) => row.map(() => false))
  const regions: Region[] = []
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (!changed[r][c] || used[r][c]) continue
      // Grow right, then down while every cell in the strip is changed.
      let w = 1
      while (c + w < cols && changed[r][c + w] && !used[r][c + w]) w++
      let h = 1
      const rowFull = (rr: number) => {
        for (let cc = c; cc < c + w; cc++)
          if (!changed[rr][cc] || used[rr][cc]) return false
        return true
      }
      while (r + h < rows && rowFull(r + h)) h++
      for (let rr = r; rr < r + h; rr++)
        for (let cc = c; cc < c + w; cc++) used[rr][cc] = true
      regions.push({ x: c / cols, y: r / rows, w: w / cols, h: h / rows })
    }
  }
  return regions
}

function computeRegions(
  baseline: HTMLImageElement,
  current: HTMLImageElement
): Region[] {
  // Compare the shared top region at a common scale — same policy as the
  // worker's layer 4 (a page that merely grew compares its shared top).
  const scale = (img: HTMLImageElement) =>
    Math.max(8, Math.round(img.naturalHeight * (COMPARE_WIDTH / img.naturalWidth)))
  const currentScaledH = scale(current)
  const height = Math.min(scale(baseline), currentScaledH, 4096)
  const b = samplePixels(baseline, COMPARE_WIDTH, height)
  const c = samplePixels(current, COMPARE_WIDTH, height)
  if (!b || !c) return []

  const cols = Math.ceil(COMPARE_WIDTH / BLOCK)
  const rows = Math.ceil(height / BLOCK)
  const changed: boolean[][] = []
  for (let r = 0; r < rows; r++) {
    changed.push([])
    for (let col = 0; col < cols; col++) {
      let sum = 0
      let n = 0
      const yEnd = Math.min((r + 1) * BLOCK, height)
      const xEnd = Math.min((col + 1) * BLOCK, COMPARE_WIDTH)
      for (let y = r * BLOCK; y < yEnd; y += 2) {
        for (let x = col * BLOCK; x < xEnd; x += 2) {
          const i = (y * COMPARE_WIDTH + x) * 4
          sum += Math.abs(luma(b, i) - luma(c, i))
          n++
        }
      }
      changed[r].push(n > 0 && sum / n > DIFF_THRESHOLD)
    }
  }
  // The overlay container is sized by the CURRENT capture, but the grid
  // covers only the compared (shared-top) region — rescale y/h so the
  // highlights sit over the right pixels when the current page is taller
  // than the compared slice.
  const yScale = height / currentScaledH
  return mergeBlocks(changed, cols, rows).map((r) => ({
    x: r.x,
    y: r.y * yScale,
    w: r.w,
    h: r.h * yScale,
  }))
}

export function VisualDiffSlider({
  baselinePath,
  currentPath,
  suppressedRegions = [],
  className,
}: {
  baselinePath: string
  currentPath: string
  /** Site bbox suppression rules — fractions of the BASELINE capture
   * (what the user drew on); rescaled here onto the current capture.
   * Drawing NEW regions happens in the suppression panel's RegionPicker
   * (on the baseline capture, matching the stored coordinate space). */
  suppressedRegions?: Region[]
  className?: string
}) {
  const baseline = useArtifact(baselinePath)
  const current = useArtifact(currentPath)
  const [divider, setDivider] = useState(0.5)
  const [regions, setRegions] = useState<Region[]>([])
  const [imagesReady, setImagesReady] = useState(false)
  // Baseline-height / current-height ratio (in width-normalized units):
  // suppression rules are fractions of the baseline capture, while the
  // container is sized by the current capture — y/h must rescale.
  const [heightRatio, setHeightRatio] = useState(1)
  const containerRef = useRef<HTMLDivElement>(null)
  const draggingDivider = useRef(false)

  // Load both images off-DOM, then diff once both have decoded.
  useEffect(() => {
    if (!baseline.url || !current.url) return
    let cancelled = false
    const load = (src: string) =>
      new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image()
        img.onload = () => resolve(img)
        img.onerror = () => reject(new Error("image load failed"))
        img.src = src
      })
    Promise.all([load(baseline.url), load(current.url)])
      .then(([b, c]) => {
        if (cancelled) return
        setImagesReady(true)
        const bAspect = b.naturalHeight / Math.max(1, b.naturalWidth)
        const cAspect = c.naturalHeight / Math.max(1, c.naturalWidth)
        setHeightRatio(cAspect > 0 ? bAspect / cAspect : 1)
        setRegions(computeRegions(b, c))
      })
      .catch(() => {
        if (!cancelled) setImagesReady(false)
      })
    return () => {
      cancelled = true
    }
  }, [baseline.url, current.url])

  const fraction = useCallback((clientX: number) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return 0.5
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  }, [])

  const onPointerMove = (e: React.PointerEvent) => {
    if (draggingDivider.current) setDivider(fraction(e.clientX))
  }
  const onPointerUp = (e: React.PointerEvent) => {
    draggingDivider.current = false
    e.currentTarget.releasePointerCapture?.(e.pointerId)
  }

  if (baseline.loading || current.loading) {
    return (
      <div className={cn("rounded-lg border border-hairline-strong bg-surface-deep p-8", className)}>
        <p className="text-body-sm text-mute">Loading screenshots…</p>
      </div>
    )
  }
  if (baseline.error || current.error || !baseline.url || !current.url) {
    return (
      <div className={cn("rounded-lg border border-hairline-strong bg-surface-deep p-8", className)}>
        <p className="text-body-sm text-mute">
          {baseline.error && current.error
            ? "Screenshots unavailable for this comparison."
            : baseline.error
              ? "Baseline screenshot unavailable."
              : "Current screenshot unavailable."}
        </p>
      </div>
    )
  }

  return (
    <div className={className}>
      <div className="mb-3 flex items-center justify-between bg-surface-elevated/20 p-1.5 rounded-lg border border-hairline">
        <span className="font-mono text-xs font-bold uppercase tracking-wider text-accent-orange select-none ml-2">
          Baseline
        </span>
        {imagesReady && (
          <span className="font-display text-xs font-medium text-ink bg-surface-card px-3 py-1 rounded-full border border-hairline-strong shadow-sm select-none">
            {regions.length === 0
              ? "No changes detected"
              : `${regions.length} altered region${regions.length === 1 ? "" : "s"} highlighted`}
          </span>
        )}
        <span className="font-mono text-xs font-bold uppercase tracking-wider text-accent-blue select-none mr-2">
          Current
        </span>
      </div>
      <div
        ref={containerRef}
        className="relative cursor-ew-resize touch-none overflow-hidden rounded-lg border border-hairline-strong bg-surface-deep select-none"
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {/* Current fills the container; baseline sits above it, clipped to
            the divider so the divider "wipes" between the two captures. */}
        <img src={current.url} alt="Current capture" className="block w-full" draggable={false} />
        <div
          className="absolute inset-0 overflow-hidden"
          style={{ width: `${divider * 100}%` }}
          aria-hidden
        >
          {/* Width is the container's size expressed relative to this
              clipped wrapper (wrapper = divider fraction of container),
              so the two captures stay pixel-aligned while the divider
              wipes. Guard: at divider 0 the wrapper is 0 wide anyway. */}
          <img
            src={baseline.url}
            alt=""
            className="block h-auto max-w-none"
            draggable={false}
            style={{ width: divider > 0.001 ? `${100 / divider}%` : "100%" }}
          />
        </div>

        {/* Altered-region overlays: translucent accent-red, hairline
            accent border — never solid fills (§4). */}
        {regions.map((r, i) => (
          <div
            key={i}
            aria-hidden
            className="pointer-events-none absolute rounded-xs"
            style={{
              left: `${r.x * 100}%`,
              top: `${r.y * 100}%`,
              width: `${r.w * 100}%`,
              height: `${r.h * 100}%`,
              backgroundColor: "rgba(255,32,71,0.28)",
              border: "1px solid rgba(255,32,71,0.55)",
            }}
          />
        ))}

        {/* Suppressed regions (existing bbox rules) — neutral hatch so
            the user sees what the engine is ignoring. Rules are baseline
            fractions; the container is current-capture sized, so y/h
            rescale through the aspect ratio. */}
        {suppressedRegions.map((r, i) => (
          <div
            key={`s${i}`}
            aria-hidden
            className="pointer-events-none absolute rounded-xs border border-hairline-strong"
            style={{
              left: `${r.x * 100}%`,
              top: `${r.y * heightRatio * 100}%`,
              width: `${r.w * 100}%`,
              height: `${r.h * heightRatio * 100}%`,
              backgroundImage:
                "repeating-linear-gradient(45deg, rgba(255,255,255,0.10) 0 6px, transparent 6px 12px)",
            }}
          />
        ))}

        {/* Divider handle. */}
        <div
            role="slider"
            aria-label="Comparison divider"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(divider * 100)}
            aria-orientation="horizontal"
            tabIndex={0}
            className="absolute inset-y-0 z-10 w-12 -translate-x-1/2 cursor-ew-resize group"
            style={{ left: `${divider * 100}%` }}
            onPointerDown={(e) => {
              draggingDivider.current = true
              e.currentTarget.setPointerCapture(e.pointerId)
              e.stopPropagation()
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") setDivider((d) => Math.max(0, d - 0.02))
              if (e.key === "ArrowRight") setDivider((d) => Math.min(1, d + 0.02))
            }}
          >
          {/* Vertical divider line - dual colored (white line, dark shadow glow) to remain visible on all image backgrounds */}
          <div className="absolute inset-y-0 left-1/2 w-[2px] -translate-x-1/2 bg-white shadow-[0_0_3px_rgba(0,0,0,0.8),0_0_1px_rgba(0,0,0,1)]" />
          
          {/* Sticky Knob wrapper - floats in the vertical center of the scroll container viewport */}
          <div className="sticky top-1/2 -translate-y-1/2 pointer-events-none flex items-center justify-center h-0 w-full">
            <div className="pointer-events-auto size-8 rounded-full border-2 border-primary bg-surface-elevated text-ink shadow-[0_2px_10px_rgba(0,0,0,0.55)] flex items-center justify-center hover:scale-105 active:scale-95 transition-transform duration-150">
              <ChevronLeft className="size-4 -mr-0.5 shrink-0 text-ink/90" />
              <ChevronRight className="size-4 -ml-0.5 shrink-0 text-ink/90" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
