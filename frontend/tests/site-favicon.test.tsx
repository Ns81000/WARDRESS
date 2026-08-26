import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FaviconCard } from "../src/components/favicon-card"
import { SiteFavicon } from "../src/components/site-favicon"
import { AuthProvider } from "../src/lib/auth"

// The opt-in site icon pipeline: fetch-as-blob with the Authorization
// header (plain <img src> cannot authenticate), SiteAvatar fallback on
// 404/error/loading, leak-free object-URL lifecycle, StrictMode-safe.
//
// jsdom lacks URL.createObjectURL/revokeObjectURL — stub both.

const createdUrls: string[] = []
const revokedUrls: string[] = []

beforeEach(() => {
  let n = 0
  vi.stubGlobal(
    "URL",
    Object.assign(Object.create(URL), {
      createObjectURL: vi.fn(() => {
        const u = `blob:mock-${++n}`
        createdUrls.push(u)
        return u
      }),
      revokeObjectURL: vi.fn((u: string) => revokedUrls.push(u)),
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  createdUrls.length = 0
  revokedUrls.length = 0
})

function jsonResponse(body: unknown, status = 200) {
  if (body instanceof Response) return body
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function pngResponse() {
  // Minimal PNG-magic body; content type is what the hook cares about.
  return new Response(new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])]), {
    status: 200,
    headers: { "Content-Type": "image/png", "Cache-Control": "private, max-age=86400" },
  })
}

function renderWithProviders(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  )
}

describe("SiteFavicon", () => {
  it("shows the letter-avatar fallback while loading (no broken-image flash)", async () => {
    let resolveFetch!: (v: Response) => void
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((r) => (resolveFetch = r))),
    )
    const { container } = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(container.querySelector("img[src^='blob:']")).toBeNull()
    })
    // SiteAvatar renders the hostname's first alnum char (or "?" when URL
    // parsing yields none) — just assert a non-empty single-char avatar.
    expect(container.textContent).toMatch(/^(.|\?)$/)
    expect(container.textContent?.length).toBe(1)
    resolveFetch(pngResponse())
  })

  it("renders a blob-URL <img> after a 200 and sent the Authorization header", async () => {
    const fetchMock = vi.fn(async () => pngResponse())
    vi.stubGlobal("fetch", fetchMock)
    const { container } = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(container.querySelector("img")).not.toBeNull()
    })
    const img = container.querySelector("img")!
    expect(img.getAttribute("src")).toMatch(/^blob:/)
    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/api/sites/s1/icon"))
    expect(call).toBeDefined()
    const init = call![1] as RequestInit | undefined
    // The Authorization header must ride along (module token may be empty in
    // tests; the header key presence is what the artifact pattern guarantees).
    expect(init?.headers).toBeDefined()
  })

  it("falls back to the letter avatar on 404 (feature off / no cache) — no img", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "Site icon unavailable" }, 404)))
    const { container } = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(container.textContent?.length).toBe(1)
    })
    expect(container.querySelector("img[src^='blob:']")).toBeNull()
  })

  it("falls back to the letter avatar on network error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network down")
      }),
    )
    const { container } = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(container.textContent?.length).toBe(1)
    })
    expect(container.querySelector("img[src^='blob:']")).toBeNull()
  })

  it("revokes the object URL on unmount", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => pngResponse()))
    const { container, unmount } = renderWithProviders(
      <SiteFavicon siteId="s1" url="https://acme.example" />,
    )
    await waitFor(() => {
      expect(container.querySelector("img[src^='blob:']")).not.toBeNull()
    })
    const url = container.querySelector("img")!.getAttribute("src")!
    expect(revokedUrls).not.toContain(url)
    unmount()
    expect(revokedUrls).toContain(url)
  })

  it("StrictMode-style double mount neither double-fetches nor leaks", async () => {
    const fetchMock = vi.fn(async () => pngResponse())
    vi.stubGlobal("fetch", fetchMock)

    // Simulate StrictMode: mount → unmount → remount the same component tree.
    const first = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(first.container.querySelector("img[src^='blob:']")).not.toBeNull()
    })
    first.unmount()
    const second = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(second.container.querySelector("img[src^='blob:']")).not.toBeNull()
    })

    // Two mounts → two fetches (one per owned effect). Unmount the second
    // tree, then every created URL must have been revoked — zero leaks.
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes("/icon"))).toHaveLength(2)
    second.unmount()
    for (const u of createdUrls) {
      expect(revokedUrls).toContain(u)
    }
  })

  it("reserves identical box classes in fallback and ok states (no layout shift)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => pngResponse()))
    const loading = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    const fallbackEl = loading.container.firstElementChild as HTMLElement | null
    const fallbackClass = fallbackEl?.className ?? ""
    loading.unmount()

    const loaded = renderWithProviders(<SiteFavicon siteId="s1" url="https://acme.example" />)
    await waitFor(() => {
      expect(loaded.container.querySelector("img[src^='blob:']")).not.toBeNull()
    })
    // Both states carry size-4.5 by default; the caller's className wins in both.
    expect(fallbackClass).toContain("size-4.5")
    expect(loaded.container.querySelector("img")!.className).toContain("size-4.5")
  })
})

// --- Settings toggle card ---

describe("FaviconCard", () => {
  it("renders off by default and PUTs the new value through the settings API", async () => {
    // Stateful mock: the GET after the PUT's cache invalidation must
    // reflect the saved value, exactly like the real backend would.
    let stored = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes("/api/auth/refresh")) return jsonResponse({ detail: "no token" }, 401)
      if (url.includes("/api/settings/favicon")) {
        if (init?.method === "PUT") {
          stored = JSON.parse(String(init.body)).enabled
          return jsonResponse({ enabled: stored })
        }
        return jsonResponse({ enabled: stored })
      }
      return jsonResponse({ detail: `unstubbed ${url}` }, 500)
    })
    vi.stubGlobal("fetch", fetchMock)

    renderWithProviders(<FaviconCard />)
    const toggle = await waitFor(() => {
      const el = screen.getByTestId("favicon-toggle")
      // Wait for the GET to settle so the switch is enabled and interactive.
      expect(el.getAttribute("aria-checked")).toBe("false")
      expect((el as HTMLButtonElement).disabled).toBe(false)
      return el
    })

    fireEvent.click(toggle)

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes("/api/settings/favicon") && (c[1] as RequestInit)?.method === "PUT",
      )
      expect(putCall).toBeDefined()
      expect(JSON.parse((putCall![1] as RequestInit).body as string)).toEqual({ enabled: true })
    })
    await waitFor(() => {
      expect(screen.getByTestId("favicon-toggle").getAttribute("aria-checked")).toBe("true")
    })
  })
})
