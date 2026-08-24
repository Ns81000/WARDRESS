import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "../src/lib/auth"
import { CustomSelect } from "../src/components/ui/select"
import { listboxAction } from "../src/lib/listbox-keys"
import { UsersCard } from "../src/components/users-card"
import { RemediationHooksPanel } from "../src/components/remediation-hooks-panel"
import { AuditPage } from "../src/pages/audit"

// Accessibility contract for the app's dropdown menus (listbox pattern):
// triggers expose aria-expanded/aria-haspopup/aria-controls, opening moves
// focus to the selected option, arrows walk the options, Enter commits,
// Escape closes back to the trigger. Previously ArrowDown left focus on the
// trigger and assistive tech got no expanded/selected state at all.

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

const UNAUTH_REFRESH = new Response(JSON.stringify({ detail: "no token" }), {
  status: 401,
})

function stubFetch(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      for (const [pattern, body] of Object.entries(routes)) {
        if (url.includes(pattern)) {
          if (body instanceof Response) return body
          return jsonResponse(body)
        }
      }
      return jsonResponse({ detail: `unstubbed ${url}` }, 500)
    })
  )
}

beforeEach(() => {})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("listboxAction keyboard model", () => {
  it("walks options with clamping at both ends", () => {
    expect(listboxAction("ArrowDown", 0, 3)).toBe("next")
    expect(listboxAction("ArrowDown", 2, 3)).toBeNull()
    expect(listboxAction("ArrowUp", 2, 3)).toBe("prev")
    expect(listboxAction("ArrowUp", 0, 3)).toBeNull()
    expect(listboxAction("Home", 2, 3)).toBe("first")
    expect(listboxAction("Home", 0, 3)).toBeNull()
    expect(listboxAction("End", 0, 3)).toBe("last")
    expect(listboxAction("End", 2, 3)).toBeNull()
  })

  it("dismisses on Tab without claiming the next focus target, commits on Enter/Space", () => {
    expect(listboxAction("Tab", 1, 3)).toBe("dismiss")
    expect(listboxAction("Enter", 1, 3)).toBe("commit")
    expect(listboxAction(" ", 0, 1)).toBe("commit")
    expect(listboxAction("Escape", 1, 3)).toBeNull()
  })
})

describe("CustomSelect listbox contract", () => {
  const OPTIONS = [
    { value: "a", label: "Alpha" },
    { value: "", label: "None (disable assistant)" },
    { value: "c", label: "Gamma" },
  ]

  function renderSelect(onChange = vi.fn()) {
    return render(
      <div>
        <label htmlFor="test-select">Pick one</label>
        <CustomSelect id="test-select" value="a" onChange={onChange} options={OPTIONS} />
      </div>
    )
  }

  it("exposes trigger state and option roles only while open", () => {
    const { container } = renderSelect()
    const trigger = container.querySelector("#test-select") as HTMLButtonElement
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByRole("option")).toBeNull()

    fireEvent.click(trigger)
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    expect(trigger.getAttribute("aria-controls")).toBeTruthy()
    const options = screen.getAllByRole("option")
    expect(options.length).toBe(3)
    // Empty-string values stay legal options (used as "None").
    expect(options[1].textContent).toContain("None (disable assistant)")
    const selected = options.find((o) => o.getAttribute("aria-selected") === "true")
    expect(selected?.textContent).toContain("Alpha")
  })

  it("opens on arrow keys and moves focus through the options", () => {
    const { container } = renderSelect()
    const trigger = container.querySelector("#test-select") as HTMLButtonElement
    fireEvent.keyDown(trigger, { key: "ArrowDown" })
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    let active = document.activeElement as HTMLElement
    expect(active.textContent).toContain("Alpha")

    fireEvent.keyDown(active, { key: "ArrowDown" })
    active = document.activeElement as HTMLElement
    expect(active.textContent).toContain("None (disable assistant)")

    fireEvent.keyDown(active, { key: "End" })
    active = document.activeElement as HTMLElement
    expect(active.textContent).toContain("Gamma")

    // Clamped at both ends: no wrap-around.
    fireEvent.keyDown(active, { key: "ArrowDown" })
    expect((document.activeElement as HTMLElement).textContent).toContain("Gamma")
    fireEvent.keyDown(document.activeElement!, { key: "Home" })
    expect((document.activeElement as HTMLElement).textContent).toContain("Alpha")
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" })
    expect((document.activeElement as HTMLElement).textContent).toContain("Alpha")

    fireEvent.keyDown(document.activeElement!, { key: "End" })
    expect((document.activeElement as HTMLElement).textContent).toContain("Gamma")
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" })
    expect((document.activeElement as HTMLElement).textContent).toContain("None (disable assistant)")
  })

  it("commits on activation, closes, and returns focus to the trigger", () => {
    const onChange = vi.fn()
    const { container } = renderSelect(onChange)
    const trigger = container.querySelector("#test-select") as HTMLButtonElement
    fireEvent.click(trigger)
    const gamma = screen
      .getAllByRole("option")
      .find((o) => o.textContent!.includes("Gamma"))!
    fireEvent.click(gamma)
    expect(onChange).toHaveBeenCalledWith("c")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)
  })

  it("commits via keyboard Enter on the focused option", () => {
    const onChange = vi.fn()
    const { container } = renderSelect(onChange)
    const trigger = container.querySelector("#test-select") as HTMLButtonElement
    fireEvent.click(trigger)
    const gamma = screen
      .getAllByRole("option")
      .find((o) => o.textContent!.includes("Gamma"))!
    gamma.focus()
    fireEvent.keyDown(gamma, { key: "Enter" })
    expect(onChange).toHaveBeenCalledWith("c")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("closes on Escape back to the trigger and on Tab without refocusing", () => {
    const onChange = vi.fn()
    const { container } = renderSelect(onChange)
    const trigger = container.querySelector("#test-select") as HTMLButtonElement

    fireEvent.click(trigger)
    fireEvent.keyDown(document.body, { key: "Escape" })
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)

    fireEvent.click(trigger)
    const first = screen.getAllByRole("option")[0]
    first.focus()
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: "Tab" })
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).not.toBe(trigger)
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe("user management role select", () => {
  const USERS = [
    { id: "u1", email: "admin@example.com", role: "admin", is_active: true, created_at: "2026-08-01T00:00:00Z" },
    { id: "u2", email: "analyst@example.com", role: "analyst", is_active: true, created_at: "2026-08-02T00:00:00Z" },
  ]
  const ADMIN = { id: "u1", email: "admin@example.com", role: "admin" }

  function usersRoutes() {
    return {
      "/api/auth/me": ADMIN,
      "/api/users/u2": jsonResponse({ ...USERS[1], role: "admin" }),
      "/api/auth/refresh": jsonResponse({ access_token: "test-token" }),
      "/api/users": USERS,
    }
  }

  function renderUsers() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <UsersCard />
        </AuthProvider>
      </QueryClientProvider>
    )
  }

  it("gives each row's role menu the full listbox contract", async () => {
    stubFetch(usersRoutes())
    const { container } = renderUsers()
    await waitFor(() => {
      expect(screen.getByText("analyst@example.com")).toBeDefined()
      // The "(you)" marker marks the signed-in admin's own row.
      expect(container.textContent).toContain("admin@example.com (you)")
    })
    // The self row renders the inert disabled branch — exactly one live
    // trigger exists, belonging to the analyst row.
    const triggers = screen
      .getAllByRole("button")
      .filter((el) => el.getAttribute("aria-haspopup") === "listbox")
    expect(triggers.length).toBe(1)
    const otherRowTrigger = triggers[0]
    expect(otherRowTrigger.getAttribute("aria-expanded")).toBe("false")

    fireEvent.click(otherRowTrigger)
    expect(otherRowTrigger.getAttribute("aria-expanded")).toBe("true")
    const options = screen.getAllByRole("option")
    expect(options.map((o) => o.textContent)).toEqual(
      expect.arrayContaining(["Admin", "Analyst", "Viewer"])
    )
    // Opening moved focus to the selected option.
    expect((document.activeElement as HTMLElement).textContent).toContain("Analyst")

    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" })
    expect((document.activeElement as HTMLElement).textContent).toContain("Admin")
    fireEvent.keyDown(document.activeElement!, { key: "Enter" })

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls as unknown as [RequestInfo | URL, RequestInit?][]
      const put = calls.find(([u]) => String(u).includes("/api/users/u2"))
      expect(put).toBeDefined()
    })
    expect(otherRowTrigger.getAttribute("aria-expanded")).toBe("false")

    fireEvent.keyDown(otherRowTrigger, { key: "Enter" })
    expect(otherRowTrigger.getAttribute("aria-expanded")).toBe("true")
    fireEvent.keyDown(document.body, { key: "Escape" })
    expect(otherRowTrigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("keeps the self row's role menu disabled and inert", async () => {
    stubFetch(usersRoutes())
    renderUsers()
    await waitFor(() => {
      expect(screen.getByText("admin@example.com")).toBeDefined()
    })
    const selfRow = screen.getByText("admin@example.com").closest("li")
    // The disabled branch renders static content — no popup affordance.
    expect(selfRow?.querySelector('[aria-haspopup="listbox"]')).toBeNull()
  })
})

describe("remediation hook action-type dropdown", () => {
  function renderPanel() {
    stubFetch({
      "/api/auth/me": { id: "u1", email: "admin@example.com", role: "admin" },
      "/api/auth/refresh": jsonResponse({ access_token: "test-token" }),
      "/api/sites/s1/remediation-hooks": [],
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RemediationHooksPanel siteId="s1" />
        </AuthProvider>
      </QueryClientProvider>
    )
  }

  it("exposes the action-type menu with roles, focus movement and Escape", async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText("No hooks configured.")).toBeDefined()
    })
    fireEvent.click(screen.getByRole("button", { name: /Add hook/ }))
    const trigger = await waitFor(() => {
      const el = document.querySelector("#hook-action") as HTMLButtonElement | null
      expect(el).not.toBeNull()
      return el!
    })
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")

    // Opening jumps to the selected option (custom_webhook — the last one).
    fireEvent.keyDown(trigger, { key: "ArrowDown" })
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    const options = screen.getAllByRole("option")
    expect(options.length).toBe(4)
    const selected = options.find((o) => o.getAttribute("aria-selected") === "true")
    expect(selected!.textContent).toContain("Custom webhook")
    expect(document.activeElement).toBe(selected)

    // Home then ArrowDown walks onto Docker restart; Enter commits it.
    fireEvent.keyDown(document.activeElement!, { key: "Home" })
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" })
    expect((document.activeElement as HTMLElement).textContent).toContain("Docker restart")
    fireEvent.keyDown(document.activeElement!, { key: "Enter" })
    expect(trigger.textContent).toContain("Docker restart")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)

    // Reopen from the keyboard, then dismiss with Escape FROM THE TRIGGER:
    // the enclosing Radix dialog must survive the same keystroke.
    fireEvent.keyDown(trigger, { key: "Enter" })
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    fireEvent.keyDown(trigger, { key: "Escape" })
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)
    // The enclosing Radix dialog survived the same keystroke.
    expect(screen.getByText("Add a remediation hook")).toBeDefined()
  })
})

describe("audit log target-type filter dropdown", () => {
  it("implements the listbox contract for filtering", async () => {
    stubFetch({
      "/api/auth/refresh": UNAUTH_REFRESH,
      "/api/audit-log": { total: 0, items: [] },
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <AuditPage />
      </QueryClientProvider>
    )
    await waitFor(() => {
      expect(container.textContent).toContain("No matching entries")
    })
    const trigger = screen.getByRole("button", { name: "All targets" })
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox")

    fireEvent.click(trigger)
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    const siteOption = screen
      .getAllByRole("option")
      .find((o) => o.textContent!.includes("site"))!
    expect(siteOption.getAttribute("aria-selected")).toBe("false")
    fireEvent.click(siteOption)
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(trigger.textContent).toContain("site")
    // The query re-fetched carrying the chosen filter.
    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls as unknown as [RequestInfo | URL][]
      expect(calls.some(([u]) => String(u).includes("target_type=site"))).toBe(true)
    })
  })
})
