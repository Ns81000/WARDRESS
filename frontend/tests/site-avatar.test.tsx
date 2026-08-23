import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SiteAvatar } from "../src/components/site-avatar"
import { siteAvatarFor } from "../src/lib/site-avatar"

// The site avatar replaces the third-party favicon <img> that previously sent
// every monitored hostname to an external service on each dashboard view. It
// must be fully local: deterministic per hostname, no network requests (i.e.
// it never renders an <img>), and robust to malformed input.
describe("siteAvatarFor", () => {
  it("is deterministic for the same URL", () => {
    const a = siteAvatarFor("https://example.com/some/path")
    const b = siteAvatarFor("https://example.com/other/path")
    expect(a).toEqual(b)
  })

  it("takes the initial from the hostname's first alphanumeric character", () => {
    expect(siteAvatarFor("https://wiki.corp.local/deep").initial).toBe("W")
    expect(siteAvatarFor("http://acme.com:8443").initial).toBe("A")
    expect(siteAvatarFor("https://9front.org").initial).toBe("9")
  })

  it("ignores scheme and path when choosing tone", () => {
    expect(siteAvatarFor("https://acme.com").tone).toBe(siteAvatarFor("http://acme.com/x?y=1").tone)
  })

  it("handles malformed URLs without throwing", () => {
    const a = siteAvatarFor("not a url at all")
    expect(a.initial).toBe("?")
    expect(a.tone).toMatch(/text-/)
  })

  it("distributes hostnames across more than one tone", () => {
    const hosts = [
      "alpha.example",
      "bravo.example",
      "charlie.example",
      "delta.example",
      "echo.example",
      "foxtrot.example",
      "golf.example",
      "hotel.example",
    ]
    const tones = new Set(hosts.map((h) => siteAvatarFor(`https://${h}`).tone))
    expect(tones.size).toBeGreaterThan(1)
  })
})

describe("SiteAvatar component", () => {
  it("renders the deterministic initial as text with no <img> element", () => {
    const { container } = render(<SiteAvatar url="https://wiki.corp.local" />)
    expect(container.querySelector("img")).toBeNull()
    expect(container.textContent).toBe("W")
  })
})
