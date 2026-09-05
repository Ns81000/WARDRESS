import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { HealthPage } from "../src/pages/health"
import { SiteDetailPage } from "../src/pages/site-detail"

// PROMPT-002 Phase 7 surfaces: the health page's capture-quality summary
// (renders exactly the buckets the API counted — no invented zeros) and
// the site-detail re-baseline hint (an old-method baseline tells the
// operator to rebaseline; both version numbers come from the payload).

function healthPayload(overrides: Record<string, unknown> = {}) {
  return {
    status: "ok",
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
      worker: { status: "ok", detail: "1 worker(s)" },
    },
    sites_with_degraded_scans: 0,
    capture_quality_summary: {},
    ...overrides,
  }
}

function sitePayload(overrides: Record<string, unknown> = {}) {
  return {
    id: "site-1",
    name: "Example",
    url: "https://example.com/",
    allow_private_networks: false,
    is_active: true,
    flag_threshold: 0.5,
    auto_scan_enabled: true,
    scan_interval_minutes: 60,
    current_interval_minutes: null,
    next_scan_at: null,
    muted_until: null,
    created_at: new Date().toISOString(),
    baseline_id: "baseline-1",
    baseline_status: "ready",
    baseline_captured_at: new Date().toISOString(),
    baseline_error: null,
    consecutive_degraded_scans: 0,
    baseline_capture_method_version: 1,
    current_capture_method_version: 2,
    needs_rebaseline: true,
    ...overrides,
  }
}

const EMPTY_SCAN_PAGE = { items: [], total: 0, offset: 0, limit: 10 }

function stubFetch(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      for (const [prefix, body] of Object.entries(routes)) {
        if (url.includes(prefix)) {
          return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        }
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    })
  )
}

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function renderHealth() {
  return renderWithQuery(<HealthPage />)
}

function renderSiteDetail() {
  return renderWithQuery(
    <MemoryRouter initialEntries={["/sites/site-1"]}>
      <Routes>
        <Route path="/sites/:siteId" element={<SiteDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe("Phase 7 capture health surfaces", () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("health page renders capture-quality buckets exactly as the API counted them", async () => {
    stubFetch({
      "/api/health/details": healthPayload({
        capture_quality_summary: { degraded: 2, full: 5 },
      }),
    })
    const { container } = renderHealth()
    await waitFor(() => {
      expect(container.textContent).toContain("Capture Quality (24h)")
      expect(container.textContent).toContain("full 5")
    })
    expect(container.textContent).toContain("degraded 2")
  })

  it("health page shows no invented zeros when no scans carry capture evidence", async () => {
    stubFetch({ "/api/health/details": healthPayload({ capture_quality_summary: {} }) })
    const { container } = renderHealth()
    await waitFor(() => {
      expect(container.textContent).toContain("no capture evidence yet")
    })
    expect(container.textContent).not.toContain("full 0")
  })

  it("site detail shows the re-baseline hint for an old-method baseline", async () => {
    stubFetch({
      "/api/sites/site-1/scans": EMPTY_SCAN_PAGE,
      "/api/sites/site-1": sitePayload(),
    })
    const { container } = renderSiteDetail()
    await waitFor(() => {
      expect(container.textContent).toContain("Capture method updated")
    })
    const text = container.textContent ?? ""
    expect(text).toContain("capture method 1")
    expect(text).toContain("current method is 2")
  })

  it("site detail shows no hint when the baseline matches the current capture method", async () => {
    stubFetch({
      "/api/sites/site-1/scans": EMPTY_SCAN_PAGE,
      "/api/sites/site-1": sitePayload({
        needs_rebaseline: false,
        baseline_capture_method_version: 2,
        current_capture_method_version: 2,
      }),
    })
    const { container } = renderSiteDetail()
    await waitFor(() => {
      expect(container.textContent).toContain("Example")
    })
    expect(container.textContent).not.toContain("Capture method updated")
  })
})