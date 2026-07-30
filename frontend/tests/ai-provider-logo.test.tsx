import { fireEvent, render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { OllamaEnableHint, ProviderLogo } from "../src/components/ai-settings-card"

// Regression guard for the previously-missing provider logo requirement
// (forensic finding C2). A logo must render as a plain <img> pointing at
// models.dev — never as inlined SVG markup (an XSS vector) — with a graceful
// fallback for ids that have no logo and for load failures.
describe("ProviderLogo", () => {
  it("renders a models.dev <img> for a catalog provider (no inlined SVG)", () => {
    const { container } = render(<ProviderLogo providerType="anthropic" />)
    const img = container.querySelector("img")
    expect(img).not.toBeNull()
    expect(img?.getAttribute("src")).toBe("https://models.dev/logos/anthropic.svg")
    // The raw SVG must never be inlined into the DOM.
    expect(container.querySelector("svg")).toBeNull()
    expect(container.innerHTML).not.toContain("<path")
  })

  it("derives the url from the provider id", () => {
    const { container } = render(<ProviderLogo providerType="google" />)
    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      "https://models.dev/logos/google.svg",
    )
  })

  it("falls back to the provider initial for a custom endpoint with no logo", () => {
    const { container } = render(<ProviderLogo providerType="openai_compatible" />)
    expect(container.querySelector("img")).toBeNull()
    expect(container.textContent).toBe("O")
  })

  it("falls back to the initial when the logo fails to load (onError)", () => {
    const { container } = render(<ProviderLogo providerType="groq" />)
    const img = container.querySelector("img")
    expect(img).not.toBeNull()
    fireEvent.error(img as HTMLImageElement)
    expect(container.querySelector("img")).toBeNull()
    expect(container.textContent).toBe("G")
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
