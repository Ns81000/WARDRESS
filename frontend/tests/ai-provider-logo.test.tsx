import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { OllamaEnableHint, ProviderLogo } from "../src/components/ai-settings-card"

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

// The local Ollama container is opt-in; when it isn't running the UI must show
// the exact enable command so an operator can turn AI on entirely from the
// dashboard flow (no env editing).
describe("OllamaEnableHint", () => {
  it("shows the docker compose profile command to enable local Ollama", () => {
    const { container } = render(<OllamaEnableHint />)
    expect(container.textContent).toContain("docker compose --profile ollama up -d")
  })
})
