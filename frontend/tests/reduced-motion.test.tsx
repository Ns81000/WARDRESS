import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { cleanup, render, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { HealthPage } from "../src/pages/health"

/*
 * Reduced-motion guards (Finding 8.4): stylesheet-driven animation must be
 * zeroed app-wide by a prefers-reduced-motion media block, and the health
 * topology's SMIL <animate> dashes plus its decorative ripple ring — which
 * CSS cannot reach — must switch off at render time under the same
 * preference.
 */

const TOPOLOGY_PAYLOAD = {
  status: "ok",
  uptime_seconds: 3725,
  queue_depth: 0,
  db_size_bytes: 1048576,
  sites_total: 4,
  scans_last_24h: 12,
  avg_scan_seconds: 8.2,
  last_scan_at: new Date(Date.now() - 120_000).toISOString(),
  last_dispatch_tick_at: new Date().toISOString(),
  components: {
    database: { status: "ok", detail: null },
    redis: { status: "ok", detail: null },
    worker: { status: "ok", detail: null },
  },
  sites_with_degraded_scans: 0,
}

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

function renderTopology() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(TOPOLOGY_PAYLOAD), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <HealthPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function renderLoadedTopology() {
  const view = renderTopology()
  // Wait until the payload has actually rendered (uptime 3725s -> "1h 2m")
  // so animation assertions cannot pass against the loading skeleton.
  await waitFor(() => {
    expect(view.container.textContent).toContain("1h 2m")
  })
  return view
}

describe("prefers-reduced-motion support", () => {
  it("index.css zeroes animations and transitions under prefers-reduced-motion", () => {
    const css = readFileSync(join(import.meta.dirname, "..", "src", "index.css"), "utf8")
    const at = css.indexOf("@media (prefers-reduced-motion: reduce)")
    expect(at).toBeGreaterThanOrEqual(0)
    const block = css.slice(at, css.indexOf("}", css.indexOf("scroll-behavior", at)))
    expect(block).toContain("animation-duration")
    expect(block).toContain("animation-iteration-count")
    expect(block).toContain("transition-duration")
    expect(block).toContain("scroll-behavior: auto")
  })

  it("topology SMIL dash animation stops when reduced motion is requested", async () => {
    stubMatchMedia(true)
    const { container } = await renderLoadedTopology()
    // Every healthy flow line would otherwise carry an indefinite SMIL pulse.
    expect(container.querySelectorAll("animate").length).toBe(0)
  })

  it("decorative ripple ring is skipped under reduced motion", async () => {
    stubMatchMedia(true)
    const { container } = await renderLoadedTopology()
    expect(container.querySelector('[class*="ripple"]')).toBeNull()
  })

  it("keeps the live topology animation when motion is not reduced", async () => {
    stubMatchMedia(false)
    const { container } = await renderLoadedTopology()
    // Control: the ambient dashes exist for users who did not opt out.
    expect(container.querySelectorAll("animate").length).toBeGreaterThan(0)
  })
})
