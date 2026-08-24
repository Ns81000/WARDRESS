import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthProvider } from "../src/lib/auth"
import { SitesPage } from "../src/pages/sites"
import { SiteDetailPage } from "../src/pages/site-detail"
import { AuditPage } from "../src/pages/audit"

// Accessibility contract for the product's core navigation surfaces: site
// rows, scan rows, audit snapshot expanders and the site-detail tab strip.
// Previously every one of these was mouse-only (onClick on a <tr>/<div>
// with no tabindex/role/ARIA state), so scans, sites and audit snapshots
// were unreachable without a pointer.

vi.mock("../src/components/incident-timeline", () => ({
  IncidentTimeline: () => <div data-testid="incident-timeline-stub" />,
}))

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

// Dispatches on the request path; unmatched API calls fail loudly (500) so
// tests cannot pass against an accidentally-unstubbed surface.
function stubFetch(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      for (const [pattern, body] of Object.entries(routes)) {
        if (url.includes(pattern)) {
          if (body instanceof Response) return body
          return jsonResponse(body)
        }
      }
      return jsonResponse({ detail: `unstubbed ${url}` }, 500)
    })
  )
}

const UNAUTH_REFRESH = new Response(JSON.stringify({ detail: "no token" }), {
  status: 401,
})

function renderWithProviders(ui: ReactNode, initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route path="/sites/:siteId" element={ui} />
            <Route path="/" element={ui} />
            <Route path="/audit" element={ui} />
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("sites table row navigation", () => {
  const SITES = [
    {
      id: "s1",
      name: "Acme Corp",
      url: "https://acme.example",
      baseline_status: "ready",
      created_at: "2026-08-01T00:00:00Z",
    },
  ]

  // Authenticated as admin so the per-row delete control renders.
  function sitesRoutes() {
    return {
      "/api/auth/me": { id: "u1", email: "admin@example.com", role: "admin" },
      "/api/auth/refresh": jsonResponse({ access_token: "test-token" }),
      "/api/sites": SITES,
    }
  }

  it("exposes each site row as a real link carrying the site name", async () => {
    stubFetch(sitesRoutes())
    renderWithProviders(<SitesPage />, "/")
    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeDefined()
    })
    const link = screen.getByRole("link", { name: "Acme Corp" })
    expect(link.getAttribute("href")).toBe("/sites/s1")
    // The link must be the row-wide hit target, not just the label text.
    expect(link.className).toContain("after:absolute")
    expect(link.className).toContain("after:inset-0")
  })

  it("navigates to the site when the row link is activated", async () => {
    stubFetch(sitesRoutes())
    const { container } = renderWithProviders(
      <>
        <SitesPage />
        <LocationProbe />
      </>,
      "/"
    )
    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeDefined()
    })
    fireEvent.click(screen.getByRole("link", { name: "Acme Corp" }))
    await waitFor(() => {
      expect(container.querySelector("[data-testid=location]")?.textContent).toBe("/sites/s1")
    })
  })

  it("keeps the per-row delete button clickable above the stretched link", async () => {
    stubFetch(sitesRoutes())
    renderWithProviders(
      <>
        <SitesPage />
        <LocationProbe />
      </>,
      "/"
    )
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete Acme Corp" })).toBeDefined()
    })
    fireEvent.click(screen.getByRole("button", { name: "Delete Acme Corp" }))
    // The confirm dialog opens instead of the row navigating.
    await waitFor(() => {
      expect(screen.getByText("Remove Site?")).toBeDefined()
    })
  })
})

describe("scan row navigation and site tabs", () => {
  const SITE = {
    id: "s1",
    name: "Acme Corp",
    url: "https://acme.example",
    baseline_status: "ready",
    baseline_id: null,
    created_at: "2026-08-01T00:00:00Z",
    flag_threshold: 0.5,
    scan_interval_minutes: 60,
    auto_scan_enabled: true,
    allow_private_networks: false,
  }
  const SCANS_PAGE = {
    total: 1,
    items: [
      {
        id: "sc1",
        status: "completed",
        verdict: "flagged",
        risk_score: 0.87,
        layer_scores: null,
        started_at: "2026-08-20T10:00:00Z",
        created_at: "2026-08-20T10:00:00Z",
        error: null,
      },
    ],
  }

  function siteDetailRoutes() {
    return {
      "/api/auth/refresh": UNAUTH_REFRESH,
      "/api/sites/s1/scans?offset=0&limit=200": SCANS_PAGE,
      "/api/sites/s1/scans": SCANS_PAGE,
      "/api/sites/s1": SITE,
    }
  }

  it("renders the tab strip with ARIA tab semantics and roving tabindex", async () => {
    stubFetch(siteDetailRoutes())
    renderWithProviders(<SiteDetailPage />, "/sites/s1")
    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeDefined()
    })
    const tabs = screen.getAllByRole("tab")
    expect(tabs.length).toBe(4)
    const overview = screen.getByRole("tab", { name: "Overview" })
    expect(overview.getAttribute("aria-selected")).toBe("true")
    expect(overview.getAttribute("tabindex")).toBe("0")
    const hooks = screen.getByRole("tab", { name: "Remediation Hooks" })
    expect(hooks.getAttribute("aria-selected")).toBe("false")
    expect(hooks.getAttribute("tabindex")).toBe("-1")
    // Each tab names its panel; the active panel exists with that id.
    expect(overview.getAttribute("aria-controls")).toBe("site-panel-overview")
    expect(document.getElementById("site-panel-overview")).not.toBeNull()
  })

  it("moves selection with the arrow keys, activation following focus", async () => {
    stubFetch(siteDetailRoutes())
    renderWithProviders(<SiteDetailPage />, "/sites/s1")
    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeDefined()
    })
    const tablist = screen.getByRole("tablist")
    fireEvent.keyDown(tablist, { key: "ArrowRight" })
    const scans = screen.getByRole("tab", { name: "Scans" })
    expect(scans.getAttribute("aria-selected")).toBe("true")
    expect(document.activeElement).toBe(scans)
    fireEvent.keyDown(tablist, { key: "ArrowLeft" })
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true")
    fireEvent.keyDown(tablist, { key: "End" })
    expect(screen.getByRole("tab", { name: "Remediation Hooks" }).getAttribute("aria-selected")).toBe("true")
    fireEvent.keyDown(tablist, { key: "Home" })
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true")
  })

  it("wraps selection past both ends of the tab strip", async () => {
    stubFetch(siteDetailRoutes())
    renderWithProviders(<SiteDetailPage />, "/sites/s1")
    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeDefined()
    })
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowLeft" })
    expect(screen.getByRole("tab", { name: "Remediation Hooks" }).getAttribute("aria-selected")).toBe("true")
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" })
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true")
  })

  it("exposes each scan row as a real link with a descriptive name", async () => {
    stubFetch(siteDetailRoutes())
    renderWithProviders(<SiteDetailPage />, "/sites/s1")
    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeDefined()
    })
    fireEvent.click(screen.getByRole("tab", { name: "Scans" }))
    const link = await waitFor(() => {
      const el = screen.getByRole("link", { name: /Open flagged scan started/ })
      expect(el.getAttribute("href")).toBe("/sites/s1/scans/sc1")
      return el
    })
    // Row-wide hit target again.
    expect(link.className).toContain("after:absolute")
  })
})

describe("audit snapshot expanders", () => {
  const PAGE = {
    total: 2,
    items: [
      {
        id: "a1",
        action: "site.create",
        target_type: "site",
        target_id: "t1",
        target_label: "Acme Corp",
        actor_email: "admin@example.com",
        created_at: "2026-08-20T10:00:00Z",
        before_json: { name: "Acme Corp (old)" },
        after_json: { name: "Acme Corp" },
      },
      {
        id: "a2",
        action: "auth.login",
        target_type: "user",
        target_id: "u1",
        target_label: "admin@example.com",
        actor_email: "admin@example.com",
        created_at: "2026-08-20T09:00:00Z",
        before_json: null,
        after_json: null,
      },
    ],
  }

  function auditRoutes() {
    return {
      "/api/auth/refresh": UNAUTH_REFRESH,
      "/api/audit-log": PAGE,
    }
  }

  it("renders detail rows as disclosure buttons wired to their panel", async () => {
    stubFetch(auditRoutes())
    const { container } = renderWithProviders(<AuditPage />, "/audit")
    await waitFor(() => {
      expect(container.textContent).toContain("site.create")
    })
    const expander = container.querySelector('li button[aria-expanded="false"]')
    expect(expander).not.toBeNull()
    const panelId = expander!.getAttribute("aria-controls")
    expect(panelId).toBeTruthy()
    // Nothing is expanded yet.
    expect(container.querySelectorAll("li div[id]").length).toBe(0)

    fireEvent.click(expander!)
    expect(expander!.getAttribute("aria-expanded")).toBe("true")
    const panel = document.getElementById(panelId!)
    expect(panel).not.toBeNull()
    expect(panel!.textContent).toContain("BEFORE_STATE")
    expect(panel!.textContent).toContain("AFTER_STATE")

    fireEvent.click(expander!)
    expect(expander!.getAttribute("aria-expanded")).toBe("false")
    expect(document.getElementById(panelId!)).toBeNull()
  })

  it("keeps rows without snapshots non-interactive", async () => {
    stubFetch(auditRoutes())
    const { container } = renderWithProviders(<AuditPage />, "/audit")
    await waitFor(() => {
      expect(container.textContent).toContain("auth.login")
    })
    // Exactly one interactive expander (the row with a snapshot); the
    // login row stays plain content.
    expect(container.querySelectorAll("li button[aria-expanded]").length).toBe(1)
    const loginRow = container.querySelector("li:nth-child(2)")
    expect(loginRow?.querySelector("button[aria-expanded]")).toBeNull()
  })
})
