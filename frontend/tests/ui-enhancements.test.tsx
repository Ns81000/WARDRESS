import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StatusDot } from "../src/components/status-dot"

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
