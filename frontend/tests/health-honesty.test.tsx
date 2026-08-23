import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { HealthPage } from "../src/pages/health"

// Data-honesty guards for the health page: every rendered value must come
// from the /api/health/details payload (or be pure formatting of it). The
// previous implementation hardcoded fabricated telemetry — a fixed 1.2 ms
// latency, a fake connection-pool reading, a permanent "operational" gateway
// status, an always-"active" Beat badge, a static sparkline sold as activity,
// and a "heartbeat signal stable" claim — none of which the API measures.
function healthPayload(overrides: Record<string, unknown> = {}) {
  return {
    status: "degraded",
    uptime_seconds: 3725,
    queue_depth: null,
    db_size_bytes: 1048576,
    sites_total: 4,
    scans_last_24h: 12,
    avg_scan_seconds: 8.2,
    last_scan_at: new Date(Date.now() - 120_000).toISOString(),
    last_dispatch_tick_at: null,
    components: {
      database: { status: "ok", detail: null },
      redis: { status: "ok", detail: null },
      worker: { status: "down", detail: "no workers responded" },
    },
    sites_with_degraded_scans: 3,
    ...overrides,
  }
}

function renderHealth(payload: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    )
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <HealthPage />
    </QueryClientProvider>
  )
}

describe("HealthPage data honesty", () => {
  beforeEach(() => {})

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders no fabricated latency, pool, broker, dispatcher or heartbeat values", async () => {
    const { container } = renderHealth(healthPayload())
    await waitFor(() => {
      expect(container.textContent).toContain("no workers responded")
    })
    const text = container.textContent ?? ""
    expect(text).not.toContain("1.2ms")
    expect(text).not.toContain("20 (active)")
    expect(text).not.toContain("thread dispatcher")
    expect(text).not.toContain("heartbeat signal stable")
    expect(text).not.toContain("redis://")
    expect(text).not.toContain("listening")
  })

  it("renders no decorative sparkline path presented as activity data", async () => {
    const { container } = renderHealth(healthPayload())
    // Wait until the payload is actually rendered (uptime 3725s -> "1h 2m")
    // so the absence check below cannot pass against the loading skeleton.
    await waitFor(() => {
      expect(container.textContent).toContain("1h 2m")
    })
    // The old static sparkline polyline, sold as live activity.
    expect(container.querySelector('path[d="M0,15 L10,12 L20,17 L30,10 L40,14 L50,6 L60,11 L70,8 L80,13 L90,4 L100,7"]')).toBeNull()
  })

  it("derives the gateway status row from the API status, not a constant", async () => {
    const { container } = renderHealth(healthPayload({ status: "degraded" }))
    await waitFor(() => {
      expect(container.textContent).toContain("DEGRADED PERFORMANCE")
    })
    // The topology details pane opens on the gateway node by default; its
    // status row must show the payload's value.
    const text = container.textContent ?? ""
    expect(text).toContain("api_core")
    expect(text).toMatch(/statusdegraded/)
    expect(text).not.toMatch(/statusoperational/)
  })

  it("shows the Beat badge as stale when no dispatch heartbeat exists", async () => {
    const { container } = renderHealth(healthPayload({ last_dispatch_tick_at: null }))
    await waitFor(() => {
      expect(container.textContent).toContain("no workers responded")
    })
    const text = container.textContent ?? ""
    expect(text).toContain("stale")
    expect(text).not.toContain("active")
  })

  it("surfaces the real worker detail instead of a placeholder", async () => {
    const { container } = renderHealth(
      healthPayload({ components: { database: { status: "ok", detail: null }, redis: { status: "ok", detail: null }, worker: { status: "down", detail: "no workers responded" } } })
    )
    await waitFor(() => {
      expect(container.textContent).toContain("no workers responded")
    })
  })

  it("reports unreadable queue depth as unknown, not zero", async () => {
    const { container } = renderHealth(healthPayload({ queue_depth: null }))
    await waitFor(() => {
      expect(container.textContent).toContain("unknown")
    })
  })

  it("renders the fleet degraded-capture count from the payload", async () => {
    const { container } = renderHealth(healthPayload({ sites_with_degraded_scans: 3 }))
    await waitFor(() => {
      expect(container.textContent).toContain("sites whose latest scan ran with failed capture/probe layers")
      expect(container.textContent).toMatch(/Degraded Captures \(24h\)3/)
    })
  })
})
