import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuditPage } from "../src/pages/audit"

// PROMPT-001 WS-D: the target-type dropdown must list EVERY target_type the
// backend writes (re-derived from record_audit call sites), and selecting
// one must filter the query by it. Three types were missing before this fix:
// ai_provider, ai_task, scan.
const ALL_TYPES = [
  "site",
  "scan",
  "suppression_rule",
  "settings",
  "notification_channel",
  "alert",
  "user",
  "api_key",
  "ai_provider",
  "ai_task",
  "remediation_hook",
  "remediation_execution",
]

const PAGE = { total: 0, items: [] }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderAudit() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("audit target-type filter completeness", () => {
  it("lists every backend-written target_type in the dropdown", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(PAGE))
    vi.stubGlobal("fetch", fetchMock)
    renderAudit()
    await waitFor(() => {
      expect(screen.getByText("All targets")).toBeDefined()
    })

    fireEvent.click(screen.getByText("All targets"))
    for (const t of ALL_TYPES) {
      expect(
        screen.getByRole("option", { name: t.replaceAll("_", " ") }),
        `dropdown option for ${t}`,
      ).toBeDefined()
    }
  })

  it("selecting ai_provider filters the query with target_type=ai_provider", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(PAGE))
    vi.stubGlobal("fetch", fetchMock)
    renderAudit()
    await waitFor(() => {
      expect(screen.getByText("All targets")).toBeDefined()
    })

    fireEvent.click(screen.getByText("All targets"))
    fireEvent.click(screen.getByRole("option", { name: "ai provider" }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("target_type=ai_provider"))
      expect(call).toBeDefined()
    })
    // The trigger now shows the humanized selection.
    expect(screen.getAllByText("ai provider").length).toBeGreaterThan(0)
  })

  it("selecting scan and ai_task each reach the API with the raw value", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(PAGE))
    vi.stubGlobal("fetch", fetchMock)

    // scan
    const first = renderAudit()
    await waitFor(() => {
      expect(screen.getByText("All targets")).toBeDefined()
    })
    fireEvent.click(screen.getByText("All targets"))
    fireEvent.click(screen.getByRole("option", { name: "scan" }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("target_type=scan"))).toBe(true)
    })
    first.unmount()

    // ai_task
    const second = renderAudit()
    await waitFor(() => {
      expect(screen.getByText("All targets")).toBeDefined()
    })
    fireEvent.click(screen.getByText("All targets"))
    fireEvent.click(screen.getByRole("option", { name: "ai task" }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("target_type=ai_task"))).toBe(true)
    })
    second.unmount()
  })
})
