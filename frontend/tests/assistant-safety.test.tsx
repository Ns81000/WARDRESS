import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import { AssistantPage } from "../src/pages/assistant"

/*
 * Assistant transcript safety (Findings 8.8/8.9):
 *  - deleting a conversation cascades its entire history server-side, so it
 *    must confirm first like every other destructive action in the dashboard;
 *  - after a stream failure the optimistic user bubble must not be duplicated
 *    by Retry, and the transcript must reconcile with what the server
 *    actually persisted.
 */

const CONVERSATIONS = [
  { id: "c1", title: "Thread A", created_at: "2026-08-25T00:00:00Z" },
]

function conversationDetail() {
  return {
    id: "c1",
    title: "Thread A",
    created_at: "2026-08-25T00:00:00Z",
    messages: [],
    pending_action: null,
  }
}

function stubAgentFetch() {
  const calls: { method: string; url: string }[] = []
  let turnAttempts = 0
  // The first turn reaches the server and is persisted before the stream
  // dies; the retried turn dies before reaching the server. The transcript
  // therefore legitimately holds exactly one persisted copy of the text.
  const persisted: {
    id: string
    role: string
    content: string
    tool_name: string | null
    created_at: string
  }[] = []
  const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    calls.push({ method, url })

    if (url.endsWith("/agent/conversations") && method === "GET") {
      return new Response(JSON.stringify(CONVERSATIONS), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }
    if (url.endsWith("/agent/conversations/c1") && method === "GET") {
      return new Response(
        JSON.stringify({
          id: "c1",
          title: "Thread A",
          created_at: "2026-08-25T00:00:00Z",
          messages: persisted.map((m) => ({ ...m })),
          pending_action: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      )
    }
    if (url.endsWith("/agent/conversations/c1") && method === "DELETE") {
      return new Response(null, { status: 204 })
    }
    if (url.endsWith("/messages") && method === "POST") {
      turnAttempts += 1
      const body = JSON.parse(String(init?.body ?? "{}"))
      if (turnAttempts === 1) {
        persisted.push({
          id: "p1",
          role: "user",
          content: body.message,
          tool_name: null,
          created_at: "2026-08-25T00:01:00Z",
        })
      }
      // The stream dies mid-turn every time (network-class failure).
      throw new Error("network down")
    }
    return new Response(JSON.stringify({}), { status: 200 })
  })
  vi.stubGlobal("fetch", fetchMock)
  return { calls, attemptCount: () => turnAttempts }
}

function renderAssistant() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AssistantPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

beforeAll(() => {
  // jsdom does not implement element scrolling; the transcript auto-scroll
  // effect calls it after every render.
  Element.prototype.scrollTo = () => {}
})

describe("conversation deletion confirmation", () => {
  it("does not delete until the operator confirms in the dialog", async () => {
    const { calls } = stubAgentFetch()
    renderAssistant()

    await waitFor(() => {
      expect(screen.getByText("Thread A")).toBeTruthy()
    })

    fireEvent.click(screen.getByLabelText("Delete conversation"))

    // The dialog appears; nothing has been deleted yet.
    expect(await screen.findByRole("dialog")).toBeTruthy()
    expect(
      calls.filter((c) => c.method === "DELETE" && c.url.includes("conversations")),
    ).toHaveLength(0)

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(
      calls.filter((c) => c.method === "DELETE" && c.url.includes("conversations")),
    ).toHaveLength(0)

    // Confirming performs exactly one DELETE.
    fireEvent.click(screen.getByLabelText("Delete conversation"))
    await screen.findByRole("dialog")
    fireEvent.click(screen.getByRole("button", { name: "Delete" }))
    await waitFor(() => {
      expect(
        calls.filter((c) => c.method === "DELETE" && c.url.includes("conversations")),
      ).toHaveLength(1)
    })
  })
})

describe("retry after a failed turn", () => {
  it("never stacks a duplicate bubble over the persisted transcript and reconciles with the server", async () => {
    const { calls, attemptCount } = stubAgentFetch()
    renderAssistant()

    await waitFor(() => {
      expect(screen.getByText("Thread A")).toBeTruthy()
    })
    // Wait for the transcript itself to finish hydrating so the optimistic
    // bubble assertions below are not racing the detail query.
    await waitFor(() => {
      expect(screen.queryByText("Loading…")).toBeNull()
    })
    const detailGetsBefore = calls.filter(
      (c) => c.method === "GET" && c.url.endsWith("/conversations/c1"),
    ).length

    // Send a message whose stream dies mid-turn.
    fireEvent.change(screen.getByPlaceholderText("Message Wardress…"), {
      target: { value: "hello thread" },
    })
    fireEvent.click(screen.getByLabelText("Send message"))

    // The optimistic bubble shows exactly once while streaming.
    await waitFor(() => {
      expect(screen.getAllByText("hello thread")).toHaveLength(1)
    })

    // The failure card appears and the transcript reconciled with the
    // server (the conversation detail was refetched).
    await screen.findByText("Something went wrong")
    await waitFor(() => {
      const detailGetsAfter = calls.filter(
        (c) => c.method === "GET" && c.url.endsWith("/conversations/c1"),
      ).length
      expect(detailGetsAfter).toBeGreaterThan(detailGetsBefore)
    })
    await waitFor(() => {
      expect(screen.queryByText("Loading…")).toBeNull()
    })
    // Reconciled to server truth: exactly the one persisted copy.
    expect(screen.getAllByText("hello thread")).toHaveLength(1)

    // Retry re-sends the failed text WITHOUT stacking a second identical
    // bubble on top of the persisted copy.
    fireEvent.click(screen.getByRole("button", { name: /Retry/i }))
    await waitFor(() => {
      expect(attemptCount()).toBe(2)
    })
    await screen.findByText("Something went wrong")
    await waitFor(() => {
      expect(screen.queryByText("Loading…")).toBeNull()
    })
    expect(screen.getAllByText("hello thread")).toHaveLength(1)
  })
})
