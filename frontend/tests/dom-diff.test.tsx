// @vitest-environment jsdom
import { describe, expect, it } from "vitest"

import { buildDomDiff } from "@/components/dom-diff-tree"
import { bboxValue, parseBboxValue } from "@/lib/bbox"

function findByTag(
  node: ReturnType<typeof buildDomDiff>,
  tag: string
): NonNullable<ReturnType<typeof buildDomDiff>>[] {
  if (!node) return []
  const hits: NonNullable<ReturnType<typeof buildDomDiff>>[] = []
  const walk = (n: NonNullable<ReturnType<typeof buildDomDiff>>) => {
    if (n.tag === tag) hits.push(n)
    n.children.forEach(walk)
  }
  walk(node)
  return hits
}

describe("buildDomDiff", () => {
  it("marks identical documents as unchanged", () => {
    const html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    const root = buildDomDiff(html, html)
    expect(root).not.toBeNull()
    expect(root!.hasChanges).toBe(false)
  })

  it("marks an injected element as added", () => {
    const before = "<html><body><h1>Hello</h1></body></html>"
    const after =
      '<html><body><h1>Hello</h1><iframe src="https://evil.example.net/"></iframe></body></html>'
    const root = buildDomDiff(before, after)
    const iframes = findByTag(root, "iframe")
    expect(iframes).toHaveLength(1)
    expect(iframes[0].state).toBe("added")
    expect(root!.hasChanges).toBe(true)
  })

  it("marks a removed element as removed and keeps it visible", () => {
    const before = '<html><body><div id="nav">Nav</div><p>Text</p></body></html>'
    const after = "<html><body><p>Text</p></body></html>"
    const root = buildDomDiff(before, after)
    const divs = findByTag(root, "div")
    expect(divs).toHaveLength(1)
    expect(divs[0].state).toBe("removed")
  })

  it("marks text changes as modified without add/remove noise", () => {
    const before = "<html><body><h1>Welcome</h1></body></html>"
    const after = "<html><body><h1>HACKED</h1></body></html>"
    const root = buildDomDiff(before, after)
    const h1 = findByTag(root, "h1")
    expect(h1).toHaveLength(1)
    expect(h1[0].state).toBe("modified")
  })

  it("pairs children by id so siblings don't cross-match", () => {
    const before =
      '<html><body><div id="a">One</div><div id="b">Two</div></body></html>'
    const after =
      '<html><body><div id="a">One</div><div id="c">Three</div></body></html>'
    const root = buildDomDiff(before, after)
    const divs = findByTag(root, "div")
    const states = divs.map((d) => d.state).sort()
    expect(states).toEqual(["added", "removed", "same"])
  })

  it("survives malformed input", () => {
    const root = buildDomDiff("<div><<<", "not html at all")
    expect(root).not.toBeNull()
  })
})

describe("bbox helpers", () => {
  it("round-trips a region through the API value format", () => {
    const region = { x: 0.125, y: 0.25, w: 0.5, h: 0.1 }
    const parsed = parseBboxValue(bboxValue(region))
    expect(parsed).not.toBeNull()
    expect(parsed!.x).toBeCloseTo(region.x, 3)
    expect(parsed!.w).toBeCloseTo(region.w, 3)
  })

  it("rejects out-of-range and malformed values", () => {
    expect(parseBboxValue("1.5,0,0.2,0.2")).toBeNull()
    expect(parseBboxValue("0,0,0,0.5")).toBeNull()
    expect(parseBboxValue("0.9,0.9,0.5,0.5")).toBeNull()
    expect(parseBboxValue("a,b,c,d")).toBeNull()
    expect(parseBboxValue("0.1,0.1,0.2")).toBeNull()
  })

  it("clamps serialized regions into 0-1", () => {
    const v = bboxValue({ x: -0.2, y: 0, w: 0.5, h: 1.4 })
    const parts = v.split(",").map(Number)
    expect(parts[0]).toBe(0)
    expect(parts[3]).toBe(1)
  })
})
