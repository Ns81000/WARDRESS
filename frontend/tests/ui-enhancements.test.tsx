import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StatusDot } from "../src/components/status-dot"
import { MarkdownMessage } from "../src/components/markdown-message"

describe("UI/UX Enhancements", () => {
  it("StatusDot maps state to the new premium glow classes", () => {
    const { container: cleanContainer } = render(<StatusDot state="clean" />)
    const cleanDot = cleanContainer.firstChild as HTMLElement
    expect(cleanDot.classList.contains("status-dot-clean")).toBe(true)

    const { container: pendingContainer } = render(<StatusDot state="pending" />)
    const pendingDot = pendingContainer.firstChild as HTMLElement
    expect(pendingDot.classList.contains("status-dot-pending")).toBe(true)

    const { container: threatContainer } = render(<StatusDot state="threat" />)
    const threatDot = threatContainer.firstChild as HTMLElement
    expect(threatDot.classList.contains("status-dot-threat")).toBe(true)

    const { container: idleContainer } = render(<StatusDot state="idle" />)
    const idleDot = idleContainer.firstChild as HTMLElement
    expect(idleDot.classList.contains("status-dot-idle")).toBe(true)
  })
})

describe("MarkdownMessage", () => {
  it("renders **bold** as a <strong> element", () => {
    const { container } = render(<MarkdownMessage content="hello **world**" />)
    const strong = container.querySelector("strong")
    expect(strong).not.toBeNull()
    expect(strong!.textContent).toBe("world")
  })

  it("renders _italic_ as an <em> element", () => {
    const { container } = render(<MarkdownMessage content="hello _world_" />)
    const em = container.querySelector("em")
    expect(em).not.toBeNull()
    expect(em!.textContent).toBe("world")
  })

  it("renders inline code as a <code> element", () => {
    const { container } = render(<MarkdownMessage content="use `npm install`" />)
    const code = container.querySelector("code")
    expect(code).not.toBeNull()
    expect(code!.textContent).toBe("npm install")
  })

  it("renders headings correctly", () => {
    const { container } = render(<MarkdownMessage content={"# Title"} />)
    expect(container.querySelector("h1")).not.toBeNull()
    expect(container.querySelector("h1")!.textContent).toBe("Title")
  })

  it("renders raw HTML as inert text, not as HTML elements (XSS guard)", () => {
    const { container } = render(
      <MarkdownMessage content='<script>alert("xss")</script>' />
    )
    // react-markdown without rehype-raw strips HTML tags entirely
    expect(container.querySelector("script")).toBeNull()
    // The text content should not contain script tags as live elements
    expect(container.innerHTML).not.toContain("<script>")
  })

  it("renders img onerror as inert text (XSS guard)", () => {
    const { container } = render(
      <MarkdownMessage content='<img onerror="alert(1)" src="x">' />
    )
    // No img element should be injected from raw HTML
    const imgs = container.querySelectorAll("img")
    // react-markdown may render markdown images but not raw HTML img tags
    for (const img of imgs) {
      expect(img.getAttribute("onerror")).toBeNull()
    }
  })

  it("returns null for empty content", () => {
    const { container } = render(<MarkdownMessage content="" />)
    expect(container.innerHTML).toBe("")
  })
})
