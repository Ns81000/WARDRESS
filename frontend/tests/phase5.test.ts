import { afterEach, describe, expect, it, vi } from "vitest"

import {
  bulkImportSites,
  confirmRemediation,
  createApiKey,
  createUser,
  getHealthDetails,
  listAuditLog,
  setAccessToken,
} from "../src/lib/api"

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("Phase 5 API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken(null)
  })

  it("createUser POSTs to /api/users with the role body", async () => {
    const seen: { url: string; init?: RequestInit }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        seen.push({ url: String(input), init })
        return jsonResponse({
          id: "u1",
          email: "a@b.com",
          role: "analyst",
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
        })
      })
    )
    setAccessToken("t")
    const user = await createUser({ email: "a@b.com", password: "a-strong-passphrase", role: "analyst" })
    expect(user.role).toBe("analyst")
    expect(seen[0].url).toBe("/api/users")
    expect(seen[0].init?.method).toBe("POST")
    expect(JSON.parse(String(seen[0].init?.body))).toMatchObject({ role: "analyst" })
  })

  it("createApiKey returns the raw key once", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          id: "k1",
          label: "ci",
          key_prefix: "wk_abc123",
          key: "wk_abc123_secretpart",
          created_at: "2026-01-01T00:00:00Z",
          last_used_at: null,
          revoked_at: null,
        })
      )
    )
    setAccessToken("t")
    const key = await createApiKey("ci")
    expect(key.key).toContain("wk_")
  })

  it("listAuditLog encodes filters as query params", async () => {
    let calledUrl = ""
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        calledUrl = String(input)
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 50 })
      })
    )
    setAccessToken("t")
    await listAuditLog({ action: "site", target_type: "settings", actor: "admin@example.com" })
    expect(calledUrl).toContain("action=site")
    expect(calledUrl).toContain("target_type=settings")
    expect(calledUrl).toContain("actor=admin%40example.com")
  })

  it("confirmRemediation POSTs to the confirm endpoint", async () => {
    let calledUrl = ""
    let method = ""
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calledUrl = String(input)
        method = init?.method ?? "GET"
        return jsonResponse({ id: "e1", status: "queued" })
      })
    )
    setAccessToken("t")
    await confirmRemediation("e1")
    expect(calledUrl).toBe("/api/remediation/executions/e1/confirm")
    expect(method).toBe("POST")
  })

  it("bulkImportSites sends csv_text", async () => {
    let body: unknown
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        body = JSON.parse(String(init?.body))
        return jsonResponse({ total_rows: 1, created: 1, skipped: 0, errors: 0, results: [] })
      })
    )
    setAccessToken("t")
    const res = await bulkImportSites({ csv_text: "https://example.com" })
    expect(res.created).toBe(1)
    expect(body).toMatchObject({ csv_text: "https://example.com" })
  })

  it("getHealthDetails reads the details endpoint", async () => {
    let calledUrl = ""
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        calledUrl = String(input)
        return jsonResponse({
          status: "ok",
          uptime_seconds: 10,
          queue_depth: 0,
          db_size_bytes: null,
          sites_total: 0,
          scans_last_24h: 0,
          avg_scan_seconds: null,
          last_scan_at: null,
          last_dispatch_tick_at: null,
          components: {},
        })
      })
    )
    setAccessToken("t")
    const h = await getHealthDetails()
    expect(h.status).toBe("ok")
    expect(calledUrl).toBe("/api/health/details")
  })
})
