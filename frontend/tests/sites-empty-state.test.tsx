import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../src/lib/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}))

import { SitesPage } from "../src/pages/sites"

/*
 * Empty-state honesty (Finding 8.5): a first-run operator must not be told
 * the product does "manual scans only" — the same create flow captures a
 * baseline immediately and every site gets adaptive scheduled scans.
 */

function renderSites() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <SitesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("sites empty state", () => {
  it("no longer claims manual-scans-only operation", async () => {
    const { container } = renderSites()
    await waitFor(() => {
      expect(container.textContent).toContain("No sites yet")
    })
    expect(container.textContent).not.toContain("manual scans only")
    expect(container.textContent).not.toContain("Phase 1")
  })

  it("describes the shipped automatic baseline and adaptive scheduling", async () => {
    const { container } = renderSites()
    await waitFor(() => {
      expect(container.textContent).toContain("No sites yet")
    })
    const text = container.textContent ?? ""
    expect(text).toContain("adaptive scheduled scans")
    expect(text).toContain("re-checks it automatically")
  })
})
