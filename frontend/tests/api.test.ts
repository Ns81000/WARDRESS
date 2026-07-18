import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { api, parseDetail, refreshSession, setAccessToken } from "../src/lib/api"

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("api client token refresh", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken(null)
  })

  it("shares one refresh call across concurrent 401s", async () => {
    let refreshCalls = 0
    let refreshed = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === "/api/auth/refresh") {
        refreshCalls += 1
        await new Promise((r) => setTimeout(r, 10))
        refreshed = true
        return jsonResponse({ access_token: "t2", token_type: "bearer", expires_in: 900 })
      }
      const auth = new Headers(init?.headers).get("Authorization")
      if (refreshed && auth === "Bearer t2") return jsonResponse([])
      return jsonResponse({ detail: "Not authenticated" }, 401)
    })
    vi.stubGlobal("fetch", fetchMock)

    setAccessToken("expired")
    const [a, b] = await Promise.all([api("/api/sites"), api("/api/sites")])
    expect(a).toEqual([])
    expect(b).toEqual([])
    expect(refreshCalls).toBe(1)
  })

  it("reports session expiry when refresh fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url === "/api/auth/refresh")
          return jsonResponse({ detail: "Invalid refresh token" }, 401)
        return jsonResponse({ detail: "Not authenticated" }, 401)
      })
    )
    setAccessToken("expired")
    await expect(api("/api/sites")).rejects.toMatchObject({ status: 401 })
  })

  it("refreshSession resolves false without a session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "No refresh token" }, 401))
    )
    const [a, b] = await Promise.all([refreshSession(), refreshSession()])
    expect(a).toBe(false)
    expect(b).toBe(false)
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1)
  })
})

describe("api client error shaping", () => {
  beforeEach(() => setAccessToken("valid"))
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken(null)
  })

  it("surfaces readable FastAPI detail strings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "A scan is already in progress" }, 409))
    )
    await expect(api("/api/sites/x/scan-now")).rejects.toMatchObject({
      status: 409,
      message: "A scan is already in progress",
    })
  })

  it("handles non-JSON error bodies gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 }))
    )
    await expect(api("/api/sites")).rejects.toMatchObject({ status: 502 })
  })

  it("returns undefined for 204 responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })))
    await expect(api("/api/sites/x", { method: "DELETE" })).resolves.toBeUndefined()
  })
})

describe("parseDetail", () => {
  it("uses a generic message for internal-looking details", async () => {
    const resp = new Response(
      JSON.stringify({
        detail: 'Traceback\n  File "/app/app/routers/sites.py", line 12',
      }),
      { status: 500 }
    )

    await expect(parseDetail(resp)).resolves.toBe(
      "Something went wrong. Please try again."
    )
  })

  it("keeps plain validation messages readable", async () => {
    const resp = new Response(JSON.stringify({ detail: "Email already exists" }), {
      status: 409,
    })

    await expect(parseDetail(resp)).resolves.toBe("Email already exists")
  })
})
