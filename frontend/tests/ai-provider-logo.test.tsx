import { readFileSync } from "node:fs"
import { join } from "node:path"

import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { OllamaEnableHint, ProviderLogo } from "../src/components/ai-settings-card"
import { PROVIDER_LOGOS } from "../src/lib/provider-logos"

// Regression guards for the third-party-leakage fix: provider logos are
// served from bundled same-origin assets (or a local letter avatar) — never
// fetched from external CDNs, and never inlined as SVG markup (an XSS
// vector). Every <img> src produced here must be same-origin.
describe("ProviderLogo", () => {
  const BUNDLED_IDS = [
    "ollama",
    "openai",
    "openai_compatible",
    "anthropic",
    "google",
    "groq",
    "mistral",
    "deepseek",
    "xai",
  ]

  it("renders a bundled same-origin <img> for a catalog provider (no remote URL, no inlined SVG)", () => {
    const { container } = render(<ProviderLogo providerType="anthropic" />)
    const img = container.querySelector("img")
    expect(img).not.toBeNull()
    const src = img?.getAttribute("src") ?? ""
    expect(/^https?:\/\//i.test(src)).toBe(false)
    // The raw SVG must never be inlined into the DOM.
    expect(container.querySelector("svg")).toBeNull()
    expect(container.innerHTML).not.toContain("<path")
  })

  it.each(BUNDLED_IDS)("keeps the logo same-origin for %s", (id) => {
    const { container } = render(<ProviderLogo providerType={id} />)
    const img = container.querySelector("img")
    expect(img).not.toBeNull()
    expect(/^https?:\/\//i.test(img?.getAttribute("src") ?? "")).toBe(false)
  })

  it("maps Custom (OpenAI-compatible) onto the OpenAI mark", () => {
    const { container: compat } = render(<ProviderLogo providerType="openai_compatible" />)
    const { container: openai } = render(<ProviderLogo providerType="openai" />)
    expect(compat.querySelector("img")?.getAttribute("src")).toBe(
      openai.querySelector("img")?.getAttribute("src"),
    )
  })

  it("falls back to the local letter avatar (no <img>, no network) for unknown providers", () => {
    const { container } = render(<ProviderLogo providerType="weirdprovider" />)
    expect(container.querySelector("img")).toBeNull()
    expect(container.textContent).toBe("W")
  })
})

// Full-map coverage: every id the map claims must resolve to a bundled
// asset that actually exists on disk — this pins the map↔file contract so a
// future edit cannot point the map at a missing file (or at a remote URL)
// without failing loudly here. Vite serves small SVGs as data: URLs in test
// mode and copies larger assets to /src/assets/providers/ paths; both are
// same-origin bundle forms, so the assertions accept exactly those two.
describe("PROVIDER_LOGOS full-map integrity", () => {
  const MAPPED_IDS = Object.keys(PROVIDER_LOGOS)

  it("covers the whole catalog-scale set with non-empty entries", () => {
    expect(MAPPED_IDS.length).toBeGreaterThan(100)
    for (const id of MAPPED_IDS) {
      expect(typeof PROVIDER_LOGOS[id]).toBe("string")
      expect((PROVIDER_LOGOS[id] as string).length).toBeGreaterThan(0)
    }
  })

  it("resolves every mapped id to a bundled same-origin asset (never a remote URL)", () => {
    const offenders: string[] = []
    for (const id of MAPPED_IDS) {
      const src = PROVIDER_LOGOS[id] as string
      const bundled =
        src.startsWith("/src/assets/providers/") || src.startsWith("data:image/svg+xml,")
      if (!bundled || /^https?:\/\//i.test(src)) offenders.push(`${id} -> ${src.slice(0, 60)}`)
    }
    expect(offenders).toEqual([])
  })

  it("has an on-disk asset file behind every mapped entry (map↔file drift tripwire)", () => {
    const assetsDir = join(__dirname, "..", "src", "assets", "providers")
    const missing: string[] = []
    for (const id of MAPPED_IDS) {
      if (id === "openai_compatible") continue // aliased to openai.svg by design
      const src = PROVIDER_LOGOS[id] as string
      // data: URLs ARE the inlined file content (Vite inlines small SVGs);
      // everything else must name a real file in assets/providers/.
      if (src.startsWith("data:image/svg+xml,")) continue
      const file = join(assetsDir, src.replace("/src/assets/providers/", ""))
      try {
        readFileSync(file)
      } catch {
        missing.push(`${id} -> ${src}`)
      }
    }
    expect(missing).toEqual([])
  })

  it("still renders a real <img> for a sample of catalog ids across the map", () => {
    for (const id of ["fireworks-ai", "zhipuai", "tencent-tokenhub", "togetherai"]) {
      if (!(id in PROVIDER_LOGOS)) continue
      const { container } = render(<ProviderLogo providerType={id} />)
      expect(container.querySelector("img"), `expected img for ${id}`).not.toBeNull()
      expect(container.innerHTML).not.toContain("<path")
    }
  })

  it("keeps letter-avatar fallback for ids deliberately left unmapped", () => {
    // These catalog ids have no obtainable mark; they must fall back locally.
    for (const id of ["lucidquery", "blueclaw"]) {
      const { container } = render(<ProviderLogo providerType={id} />)
      expect(container.querySelector("img")).toBeNull()
    }
  })
})

// The local Ollama container is opt-in; when it isn't running the UI must show
// the exact enable command so an operator can turn AI on entirely from the
// dashboard flow (no env editing).
describe("OllamaEnableHint", () => {
  it("shows the docker compose profile command to enable local Ollama", () => {
    const { container } = render(<OllamaEnableHint />)
    expect(container.textContent).toContain("docker compose --profile ollama up -d")
  })
})
