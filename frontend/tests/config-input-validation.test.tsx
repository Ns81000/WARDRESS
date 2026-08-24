import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../src/lib/api"
import { assignModelToTasks } from "../src/lib/ai-task-assignment"
import {
  parseDecimalInRange,
  parsePort,
} from "../src/lib/numeric-inputs"

/*
 * Strict config-input validation (Finding 8.7): numeric fields must never
 * silently coerce garbage to defaults — a hook threshold of "abc" used to
 * submit 0.5, an SMTP port of "abc" submitted 587 (and a blank threshold a
 * fire-on-everything 0), and failed AI task auto-assignments were swallowed
 * so the dialog reported success regardless.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}))

import { toast } from "sonner"
import { SmtpCard } from "../src/pages/settings"

describe("numeric-input parsers", () => {
  it("parseDecimalInRange accepts in-range decimals including both bounds and zero", () => {
    expect(parseDecimalInRange("0.5", 0, 1)).toBe(0.5)
    expect(parseDecimalInRange("0", 0, 1)).toBe(0)
    expect(parseDecimalInRange("1", 0, 1)).toBe(1)
    expect(parseDecimalInRange(" 0.25 ", 0, 1)).toBe(0.25)
  })

  it("parseDecimalInRange rejects blank, whitespace, garbage and out-of-range input", () => {
    expect(parseDecimalInRange("", 0, 1)).toBeNull()
    expect(parseDecimalInRange("   ", 0, 1)).toBeNull()
    expect(parseDecimalInRange("abc", 0, 1)).toBeNull()
    expect(parseDecimalInRange("0.5abc", 0, 1)).toBeNull()
    expect(parseDecimalInRange("-0.1", 0, 1)).toBeNull()
    expect(parseDecimalInRange("1.01", 0, 1)).toBeNull()
    expect(parseDecimalInRange("NaN", 0, 1)).toBeNull()
  })

  it("parsePort accepts whole ports within 1-65535 only", () => {
    expect(parsePort("587")).toBe(587)
    expect(parsePort("1")).toBe(1)
    expect(parsePort("65535")).toBe(65535)
    expect(parsePort(" 25 ")).toBe(25)
    expect(parsePort("abc")).toBeNull()
    expect(parsePort("")).toBeNull()
    expect(parsePort("   ")).toBeNull()
    expect(parsePort("58.7")).toBeNull()
    expect(parsePort("0")).toBeNull()
    expect(parsePort("70000")).toBeNull()
    expect(parsePort("-25")).toBeNull()
  })
})

describe("AI task assignment collection", () => {
  it("collects per-task failures with their API messages instead of throwing", async () => {
    const failures = await assignModelToTasks(
      async (task) => {
        if (task === "agent_chat") throw new ApiError(500, "model rejected")
        return {}
      },
      [
        { task: "explanation", wanted: true },
        { task: "agent_chat", wanted: true },
      ],
    )
    expect(failures).toEqual([{ task: "agent_chat", message: "model rejected" }])
  })

  it("maps non-API errors to a safe message and skips unwanted tasks", async () => {
    const assigned: string[] = []
    const failures = await assignModelToTasks(
      async (task) => {
        assigned.push(task)
        if (task === "explanation") throw new Error("socket hung up")
        return {}
      },
      [
        { task: "explanation", wanted: true },
        { task: "agent_chat", wanted: false },
      ],
    )
    expect(assigned).toEqual(["explanation"])
    expect(failures).toEqual([{ task: "explanation", message: "request failed" }])
  })

  it("returns no failures when every wanted assignment succeeds", async () => {
    const failures = await assignModelToTasks(async () => ({}), [
      { task: "explanation", wanted: true },
      { task: "agent_chat", wanted: true },
    ])
    expect(failures).toEqual([])
  })
})

// The provider dialog must no longer swallow assignment errors silently.
describe("ai-settings-card assignment surfacing (source pin)", () => {
  const sourceOf = (path: string) => readFileSync(join(import.meta.dirname, path), "utf8")

  it("contains no bare silent catch blocks around assignments", () => {
    const src = sourceOf("../src/components/ai-settings-card.tsx")
    expect(src).not.toMatch(/catch\s*\{/)
  })

  it("routes assignments through the failure-collecting helper", () => {
    const src = sourceOf("../src/components/ai-settings-card.tsx")
    expect(src).toContain("assignModelToTasks")
    expect(src).toContain("assignmentFailures")
  })
})

describe("SMTP port validation (SmtpCard)", () => {
  let calls: { url: string; method: string; body: string | null }[]

  function renderCard() {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? "GET"
        const body = typeof init?.body === "string" ? init.body : null
        calls.push({ url, method, body })
        if (url.endsWith("/settings/smtp") && method === "GET") {
          return new Response(
            JSON.stringify({
              configured: true,
              host: "smtp.example.com",
              port: 2525,
              security: "starttls",
              username: null,
              has_password: false,
              from_addr: "wardress@example.com",
              from_name: null,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response(JSON.stringify({ ok: true, detail: "sent" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <SmtpCard />
      </QueryClientProvider>,
    )
  }

  beforeEach(() => {
    calls = []
    vi.clearAllMocks()
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  async function openReadyForm() {
    renderCard()
    // Hydration fills host/port/from from the stored settings.
    await waitFor(() => {
      expect((screen.getByLabelText("Server host") as HTMLInputElement).value).toBe(
        "smtp.example.com",
      )
    })
    fireEvent.change(screen.getByLabelText("Send a test to"), {
      target: { value: "you@example.com" },
    })
  }

  async function expectRejectedPort(portValue: string) {
    await openReadyForm()
    fireEvent.change(screen.getByLabelText("Port"), { target: { value: portValue } })
    fireEvent.click(screen.getByRole("button", { name: /Send test/i }))
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Port must be a whole number between 1 and 65535",
      )
    })
    expect(calls.some((c) => c.url.endsWith("/smtp/test"))).toBe(false)
  }

  it("rejects non-numeric ports without issuing any request", async () => {
    await expectRejectedPort("abc")
  })

  it("rejects a cleared port field instead of submitting a default", async () => {
    await expectRejectedPort("")
  })

  it("rejects out-of-range ports", async () => {
    await expectRejectedPort("70000")
  })

  it("submits the typed port verbatim when valid", async () => {
    await openReadyForm()
    fireEvent.change(screen.getByLabelText("Port"), { target: { value: "25" } })
    fireEvent.click(screen.getByRole("button", { name: /Send test/i }))
    await waitFor(() => {
      const testCall = calls.find((c) => c.url.endsWith("/smtp/test"))
      expect(testCall).toBeDefined()
      const payload = JSON.parse(testCall!.body ?? "{}")
      expect(payload.settings.port).toBe(25)
    })
    expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining("Port"))
  })
})
