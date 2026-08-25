import { cleanup, fireEvent, render, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { ScanFinding } from "../src/lib/api"
import { DomDiffTree } from "../src/components/dom-diff-tree"
import { FindingCard } from "../src/components/finding-card"

// Render-with-adversarial-fixtures coverage for the two evidence-rendering
// components that had none: FindingCard (per-layer evidence dicts carry
// attacker-controlled page text — matched signatures, URLs, header values)
// and DomDiffTree (parses captured HTML into inert documents; captured HTML
// must never execute in the dashboard origin).

function finding(overrides: Partial<ScanFinding>): ScanFinding {
  return {
    id: "f-1",
    layer: 5,
    layer_key: "layer5_signatures",
    score: 1,
    skipped: false,
    evidence: {},
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("FindingCard renders hostile evidence inertly", () => {
  it("renders matched page text (including markup payloads) as text only", () => {
    const { container } = render(
      <FindingCard
        finding={finding({
          evidence: {
            signature_matches: [
              { matched: "<img src=x onerror=alert(1)> HACKED BY CREW", weight: 1 },
              { matched: "pwn3d by <script>alert(2)</script>", weight: 0.55 },
            ],
            profanity_matches: ["sh1t"],
          },
        })}
      />
    )
    const text = container.textContent ?? ""
    expect(text).toContain("HACKED BY CREW")
    expect(text).toContain("strong")
    expect(text).toContain("medium")
    // Hostile strings survive only as display text — never as live elements.
    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("script")).toBeNull()
  })

  it("renders attacker URLs as inert list text, not links", () => {
    const { container } = render(
      <FindingCard
        finding={finding({
          layer: 3,
          layer_key: "layer3_link_audit",
          score: 0.8,
          evidence: {
            script_src: {
              added_count: 1,
              removed_count: 0,
              added: ['https://evil.example.net/x.js"><b>payload'],
              added_new_domains: ['https://evil.example.net/x.js"><b>payload'],
              removed: [],
            },
          },
        })}
      />
    )
    const text = container.textContent ?? ""
    expect(text).toContain("evil.example.net")
    expect(text).toContain("Pointing at never-seen domains")
    expect(container.querySelectorAll("a")).toHaveLength(0)
    expect(container.querySelector("b")).toBeNull()
  })

  it("renders the directional header-diff taxonomy including attacker-influenced values as text", () => {
    const { container } = render(
      <FindingCard
        finding={finding({
          layer: 6,
          layer_key: "layer6_security_metadata",
          score: 0.4,
          evidence: {
            tls: {
              fingerprint_changed: true,
              issuer_changed: true,
              baseline_issuer: "Legit CA",
              current_issuer: "<script>evil()</script> CA",
              current_not_after: "2027-01-01T00:00:00Z",
            },
            headers: {
              security_headers_removed: ["content-security-policy"],
              security_headers_weakened: [
                {
                  header: "strict-transport-security",
                  baseline: "max-age=31536000; includeSubDomains",
                  current: "max-age=600<img onerror=1>",
                },
              ],
              security_headers_strengthened: [
                { header: "x-frame-options", baseline: "SAMEORIGIN", current: "DENY" },
              ],
              security_headers_changed: [
                { header: "referrer-policy", baseline: "no-referrer", current: "garbage" },
              ],
            },
            robots_txt: {},
          },
        })}
      />
    )
    const text = container.textContent ?? ""
    expect(text).toContain("strict-transport-security weakened")
    expect(text).toContain("x-frame-options strengthened")
    expect(text).toContain("referrer-policy changed")
    expect(text).toContain("Removed:")
    expect(text).toContain("<script>evil()</script> CA")
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img")).toBeNull()
  })

  it("shows a skipped layer's reason and never its renderer", async () => {
    const { container } = render(
      <FindingCard
        finding={finding({ skipped: true, score: null, evidence: { reason: "gated by layer 1" } })}
      />
    )
    // Skipped findings start collapsed (they are never "signaled"); expand.
    fireEvent.click(container.querySelector("button")!)
    await waitFor(() => {
      expect(container.textContent).toContain("gated by layer 1")
    })
  })

  it("falls back to generic key/value rendering for unrecognized layers (no silent drop)", () => {
    const { container } = render(
      <FindingCard
        finding={finding({
          layer: 9,
          layer_key: "layer99_something_new",
          score: 0.9,
          evidence: { novel_signal: 0.75, note: "<b>hi</b>" },
        })}
      />
    )
    const text = container.textContent ?? ""
    expect(text).toContain("novel_signal")
    expect(text).toContain("0.75")
    expect(text).toContain("<b>hi</b>")
    expect(container.querySelector("b")).toBeNull()
  })

  it("flags suppression-applied comparisons and shows skip entries in fusion inputs", () => {
    const { container } = render(
      <FindingCard
        finding={finding({
          layer: 9,
          layer_key: "layer9_fusion",
          score: 0.7,
          evidence: {
            model: "fusion-model",
            features: { layer5_signatures: 0.9, layer2_dom_structure: 0.0 },
            layers_ran: { layer5_signatures: true, layer2_dom_structure: false },
          },
        })}
      />
    )
    const text = container.textContent ?? ""
    expect(text).toContain("fusion-model")
    expect(text).toContain("skip")
  })
})

const BENIGN_HTML = "<html><body><h1>Hello</h1><p>World</p></body></html>"
const HOSTILE_HTML =
  '<html><body><h1>Hello</h1>' +
  "<script>window.__pwned = 1</script>" +
  '<img src=x onerror="alert(1)">' +
  '<iframe src="javascript:alert(2)"></iframe>' +
  "</body></html>"

function stubArtifacts(
  paths: { baseline: string; current: string },
  bodies: { baseline: string; current: string | null }
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: unknown) => {
      if (path === paths.current) {
        if (bodies.current === null) return new Response("gone", { status: 404 })
        return new Response(bodies.current)
      }
      return new Response(bodies.baseline)
    })
  )
}

describe("DomDiffTree keeps captured HTML inert", () => {
  it("renders injected hostile markup as diff text — never as live elements", async () => {
    stubArtifacts({ baseline: "/api/artifacts/b.html", current: "/api/artifacts/c.html" }, { baseline: BENIGN_HTML, current: HOSTILE_HTML })
    const { container } = render(
      <DomDiffTree baselineHtmlPath="/api/artifacts/b.html" currentHtmlPath="/api/artifacts/c.html" />
    )
    await waitFor(() => {
      expect(container.textContent).toContain("window.__pwned = 1")
    })
    const text = container.textContent ?? ""
    expect(text).toContain("added")
    expect(text).toContain("javascript:alert(2)")
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("iframe")).toBeNull()
  })

  it("reports unavailable snapshots instead of rendering anything", async () => {
    stubArtifacts({ baseline: "/a", current: "/c" }, { baseline: BENIGN_HTML, current: null })
    const { container } = render(
      <DomDiffTree baselineHtmlPath="/a" currentHtmlPath="/c" />
    )
    await waitFor(() => {
      expect(container.textContent).toContain("DOM snapshots unavailable")
    })
    expect(container.querySelector("button")).toBeNull()
  })

  it("shows the loading state while artifacts fetch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {}))
    )
    const { container } = render(
      <DomDiffTree baselineHtmlPath="/a" currentHtmlPath="/c" />
    )
    expect(container.textContent).toContain("Loading DOM snapshots")
  })
})
