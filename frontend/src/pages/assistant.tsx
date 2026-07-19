import { useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  SendHorizonal,
  Trash2,
  Wrench,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { WardressMark } from "@/components/wardress-mark"
import { cn } from "@/lib/utils"
import * as apiClient from "@/lib/api"
import {
  ApiError,
  type AgentConversation,
  type AgentMessage,
  type AgentPendingAction,
  type AgentStreamEvent,
} from "@/lib/api"

/*
 * Assistant — a full-bleed, full-height chat surface (ChatGPT/Gemini style).
 * The app shell drops its centered content column for /assistant so this
 * page owns the viewport below the nav: a collapsible thread rail on the
 * left, a centered reading column of messages that scrolls, and a composer
 * pinned to the bottom. Follows DESIGN-resend.md — true-black canvas,
 * hairline borders, one bright primary action, accents as text washes only.
 * The turn streams over a fetch-stream reader (streamAgentTurn) because the
 * access token lives in module memory — native EventSource can't set the
 * header.
 */

// A tool-activity chip shown inline while the turn runs.
interface ToolChip {
  id: string
  tool: string
  label: string
  state: "start" | "done"
  ok?: boolean
}

const TOOL_LABELS: Record<string, string> = {
  list_sites: "Listing sites",
  get_site: "Reading site",
  get_status_overview: "Checking status",
  list_scans: "Listing scans",
  get_scan_findings: "Reading findings",
  list_alerts: "Listing alerts",
  explain_incident: "Explaining incident",
  run_scan_now: "Starting a scan",
  acknowledge_alert: "Acknowledging alert",
  mute_site: "Muting site",
  unmute_site: "Unmuting site",
  add_site: "Adding site",
  rebaseline_site: "Rebaselining",
  set_flag_threshold: "Adjusting threshold",
  set_scan_interval: "Adjusting interval",
  create_suppression_rule: "Adding suppression rule",
  delete_site: "Deleting site",
}

// Starter prompts shown on an empty thread — one tap to get going.
const SUGGESTIONS = [
  "What's the status of all my sites?",
  "Which sites have unacknowledged alerts?",
  "Scan my most recently changed site now",
  "Explain the latest incident in plain English",
]

function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool.replace(/_/g, " ")
}

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

export function AssistantPage() {
  const queryClient = useQueryClient()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [railOpen, setRailOpen] = useState(true)

  const conversations = useQuery({
    queryKey: ["agent", "conversations"],
    queryFn: apiClient.listConversations,
  })

  // On first load (or after a delete), settle on a conversation to show.
  useEffect(() => {
    if (!conversations.data) return
    if (activeId && conversations.data.some((c) => c.id === activeId)) return
    setActiveId(conversations.data[0]?.id ?? null)
  }, [conversations.data, activeId])

  const createConv = useMutation({
    mutationFn: apiClient.createConversation,
    onSuccess: (conv) => {
      void queryClient.invalidateQueries({ queryKey: ["agent", "conversations"] })
      setActiveId(conv.id)
    },
    onError: (err) => toast.error(errMessage(err, "Could not start a conversation")),
  })

  const deleteConv = useMutation({
    mutationFn: apiClient.deleteConversation,
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({ queryKey: ["agent", "conversations"] })
      if (activeId === id) setActiveId(null)
    },
    onError: (err) => toast.error(errMessage(err, "Could not delete the conversation")),
  })

  return (
    <div className="relative flex h-full min-h-0 overflow-hidden">
      {/* Ambient background glow — a single blue wash anchored top-centre. */}
      <div className="pointer-events-none absolute top-[-160px] left-1/2 h-[420px] w-full max-w-[900px] -translate-x-1/2 rounded-full bg-glow-blue opacity-[0.06] blur-[160px]" />

      <ConversationRail
        open={railOpen}
        conversations={conversations.data ?? []}
        loading={conversations.isLoading}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={() => createConv.mutate()}
        onDelete={(id) => deleteConv.mutate(id)}
        creating={createConv.isPending}
      />

      <ChatPanel
        key={activeId ?? "empty"}
        conversationId={activeId}
        railOpen={railOpen}
        onToggleRail={() => setRailOpen((v) => !v)}
        onStartFirst={() => createConv.mutate()}
        creating={createConv.isPending}
      />
    </div>
  )
}

// --- Conversation rail ---

function ConversationRail({
  open,
  conversations,
  loading,
  activeId,
  onSelect,
  onNew,
  onDelete,
  creating,
}: {
  open: boolean
  conversations: AgentConversation[]
  loading: boolean
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  creating: boolean
}) {
  return (
    <aside
      className={cn(
        "relative z-10 flex h-full shrink-0 flex-col border-r border-hairline bg-surface-card/40 transition-[width] duration-200 ease-out",
        open ? "w-72" : "w-0 overflow-hidden border-r-0"
      )}
    >
      <div className="flex items-center gap-2 px-3 py-3">
        <Button
          className="flex-1 justify-start"
          variant="outline"
          size="sm"
          onClick={onNew}
          disabled={creating}
        >
          {creating ? <Loader2 className="animate-spin" /> : <Plus />}
          New chat
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <p className="px-2 py-3 text-body-sm text-mute">Loading…</p>
        ) : conversations.length === 0 ? (
          <p className="px-2 py-3 text-body-sm text-mute">
            No conversations yet. Start one to chat with Wardress.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((conv) => (
              <li key={conv.id}>
                <div
                  className={cn(
                    "group flex items-center gap-2 rounded-md px-2.5 py-2 transition-colors",
                    conv.id === activeId
                      ? "bg-surface-elevated"
                      : "hover:bg-surface-elevated/60"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(conv.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span
                      className={cn(
                        "block truncate text-body-sm",
                        conv.id === activeId ? "text-ink" : "text-charcoal"
                      )}
                    >
                      {conv.title || "New conversation"}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label="Delete conversation"
                    onClick={() => onDelete(conv.id)}
                    className="shrink-0 text-mute opacity-0 transition-opacity hover:text-accent-red group-hover:opacity-100 focus-visible:opacity-100"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}

// --- Chat panel ---

// A transcript entry: either a persisted/streamed message or a live tool chip
// group. We keep messages and the in-flight assistant draft in local state.
interface DraftState {
  text: string
  tools: ToolChip[]
  streaming: boolean
}

function ChatPanel({
  conversationId,
  railOpen,
  onToggleRail,
  onStartFirst,
  creating,
}: {
  conversationId: string | null
  railOpen: boolean
  onToggleRail: () => void
  onStartFirst: () => void
  creating: boolean
}) {
  const queryClient = useQueryClient()
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [pending, setPending] = useState<AgentPendingAction | null>(null)
  const [draft, setDraft] = useState<DraftState>({ text: "", tools: [], streaming: false })
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-grow the composer up to its max-height as the user types.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "0px"
    el.style.height = `${Math.min(el.scrollHeight, 176)}px`
  }, [input])

  const detail = useQuery({
    queryKey: ["agent", "conversation", conversationId],
    queryFn: () => apiClient.getConversation(conversationId as string),
    enabled: !!conversationId,
  })

  // Hydrate local transcript when the loaded conversation changes.
  useEffect(() => {
    if (detail.data) {
      // Tool rows are internal bookkeeping; the transcript shows user +
      // assistant prose only (tool activity is surfaced live as chips).
      setMessages(detail.data.messages.filter((m) => m.role !== "tool"))
      setPending(detail.data.pending_action)
    }
  }, [detail.data])

  // Auto-scroll to the newest content as it arrives.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages, draft])

  // Abort any in-flight stream when leaving the conversation.
  useEffect(() => () => abortRef.current?.abort(), [])

  const refreshList = () =>
    queryClient.invalidateQueries({ queryKey: ["agent", "conversations"] })

  async function send(text: string) {
    if (!conversationId || draft.streaming) return
    const trimmed = text.trim()
    if (!trimmed) return

    setInput("")
    // Optimistically append the user turn.
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`,
        role: "user",
        content: trimmed,
        tool_name: null,
        created_at: new Date().toISOString(),
      },
    ])
    setDraft({ text: "", tools: [], streaming: true })

    const controller = new AbortController()
    abortRef.current = controller
    try {
      await apiClient.streamAgentTurn(
        conversationId,
        trimmed,
        (event) => handleEvent(event),
        controller.signal
      )
    } catch (err) {
      if (!controller.signal.aborted) {
        setDraft((d) => ({ ...d, streaming: false }))
        toast.error(errMessage(err, "The assistant stream failed"))
      }
    } finally {
      abortRef.current = null
      void refreshList()
    }
  }

  function handleEvent(event: AgentStreamEvent) {
    if (event.type === "tool") {
      const tool = event.data?.tool ?? "tool"
      const state = event.data?.state ?? "start"
      setDraft((d) => {
        const tools = [...d.tools]
        // A "done" event resolves the matching in-flight chip.
        const idx = tools.findIndex((t) => t.tool === tool && t.state === "start")
        if (state === "done" && idx !== -1) {
          tools[idx] = { ...tools[idx], state: "done", ok: event.data?.ok }
        } else {
          tools.push({
            id: `${tool}-${tools.length}-${Date.now()}`,
            tool,
            label: event.text || toolLabel(tool),
            state,
            ok: event.data?.ok,
          })
        }
        return { ...d, tools }
      })
    } else if (event.type === "confirm") {
      // A high-impact action is frozen — surface the confirmation card and
      // stop streaming; the turn resumes via the confirm endpoint.
      const data = event.data
      if (data?.action_id) {
        setPending({
          id: data.action_id,
          tool: data.tool ?? "",
          summary: data.summary ?? event.text ?? null,
          status: "pending",
          expires_at: "",
        })
      }
      setDraft((d) => ({ ...d, streaming: false }))
    } else if (event.type === "done") {
      const finalText = event.text ?? ""
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: finalText,
          tool_name: null,
          created_at: new Date().toISOString(),
        },
      ])
      setDraft({ text: "", tools: [], streaming: false })
    } else if (event.type === "error") {
      setDraft((d) => ({ ...d, streaming: false }))
      toast.error(event.text || "The assistant hit an error.")
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void send(input)
  }

  // Confirm / cancel a pending high-impact action, then continue the thread
  // so the model can report the outcome.
  async function resolvePending(confirm: boolean) {
    if (!pending) return
    const action = pending
    setPending(null)
    try {
      if (confirm) {
        await apiClient.confirmAgentAction(action.id)
        toast.success("Action confirmed")
      } else {
        await apiClient.cancelAgentAction(action.id)
        toast.message("Action cancelled")
      }
    } catch (err) {
      toast.error(errMessage(err, confirm ? "Could not confirm the action" : "Could not cancel"))
      setPending(action)
      return
    }
    // Reload the transcript so the executed/cancelled outcome is reflected.
    void detail.refetch()
    void refreshList()
  }

  const empty = messages.length === 0 && !draft.streaming

  return (
    <section className="relative z-10 flex h-full min-w-0 flex-1 flex-col">
      {/* Slim header: rail toggle + thread title. */}
      <header className="flex h-12 shrink-0 items-center gap-2 px-3">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onToggleRail}
          aria-label={railOpen ? "Hide conversations" : "Show conversations"}
        >
          {railOpen ? <PanelLeftClose /> : <PanelLeftOpen />}
        </Button>
        <span className="truncate text-body-sm text-charcoal">
          {detail.data?.title || "Assistant"}
        </span>
      </header>

      {!conversationId ? (
        <EmptyState onStartFirst={onStartFirst} creating={creating} />
      ) : (
        <>
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
              {detail.isLoading ? (
                <p className="text-body-sm text-mute">Loading…</p>
              ) : empty ? (
                <WelcomeState onPick={(q) => void send(q)} />
              ) : (
                <div className="space-y-6">
                  {messages.map((msg) => (
                    <MessageRow key={msg.id} message={msg} />
                  ))}
                </div>
              )}

              {/* Live assistant draft: tool chips while working, then a
                  thinking indicator. Final prose arrives on `done`. */}
              {draft.streaming && (
                <div className="mt-6 flex flex-col gap-2">
                  {draft.tools.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {draft.tools.map((chip) => (
                        <ToolActivityChip key={chip.id} chip={chip} />
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-2 text-body-sm text-mute">
                    <Loader2 className="size-3.5 animate-spin" />
                    Thinking…
                  </div>
                </div>
              )}

              {pending && (
                <div className="mt-6">
                  <ConfirmationCard action={pending} onResolve={resolvePending} />
                </div>
              )}
            </div>
          </div>

          {/* Composer pinned to the bottom, centered on the reading column. */}
          <div className="shrink-0 px-4 pb-4 sm:px-6">
            <form onSubmit={onSubmit} className="mx-auto w-full max-w-3xl">
              <div className="flex items-end gap-2 rounded-2xl border border-hairline-strong bg-surface-card p-2 transition-colors focus-within:border-ink/50">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault()
                      void send(input)
                    }
                  }}
                  rows={1}
                  placeholder={
                    pending ? "Confirm or cancel the pending action above…" : "Message Wardress…"
                  }
                  disabled={draft.streaming || !!pending}
                  className="max-h-44 min-h-[36px] flex-1 resize-none self-center bg-transparent px-2.5 py-1.5 text-body-sm text-ink outline-none placeholder:text-mute disabled:cursor-not-allowed disabled:opacity-50"
                />
                <Button
                  type="submit"
                  size="icon"
                  className="rounded-xl"
                  disabled={!input.trim() || draft.streaming || !!pending}
                  aria-label="Send message"
                >
                  {draft.streaming ? <Loader2 className="animate-spin" /> : <SendHorizonal />}
                </Button>
              </div>
              <p className="mt-2 text-center text-caption text-mute">
                Wardress acts with your role&rsquo;s permissions. High-impact actions ask first.
              </p>
            </form>
          </div>
        </>
      )}
    </section>
  )
}

// --- Empty / welcome states ---

function EmptyState({
  onStartFirst,
  creating,
}: {
  onStartFirst: () => void
  creating: boolean
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 text-center">
      <WardressMark size={40} />
      <h2 className="mt-5 font-display text-heading-md text-ink">How can I help?</h2>
      <p className="mt-2 max-w-md text-body-sm text-charcoal">
        The assistant reads status, runs scans, and manages sites through the
        same guarded actions the dashboard uses.
      </p>
      <Button className="mt-6" onClick={onStartFirst} disabled={creating}>
        {creating ? <Loader2 className="animate-spin" /> : <Plus />}
        New chat
      </Button>
    </div>
  )
}

function WelcomeState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center pt-[8vh] text-center">
      <WardressMark size={40} />
      <h2 className="mt-5 font-display text-heading-md text-ink">How can I help?</h2>
      <p className="mt-2 max-w-md text-body-sm text-charcoal">
        Ask about your sites, scans, or alerts — or pick a starting point.
      </p>
      <div className="mt-7 grid w-full max-w-xl gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="rounded-xl border border-hairline-strong bg-surface-card px-4 py-3 text-left text-body-sm text-charcoal transition-colors hover:border-ink/40 hover:text-ink"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

// --- Message row ---

function MessageRow({ message }: { message: AgentMessage }) {
  const isUser = message.role === "user"
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface-elevated px-4 py-2.5 text-body-sm text-ink">
          {message.content}
        </div>
      </div>
    )
  }
  // Assistant: full-width plain prose with a small mark, ChatGPT-style.
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-hairline-strong bg-surface-card">
        <WardressMark size={15} />
      </div>
      <div className="min-w-0 flex-1 whitespace-pre-wrap pt-0.5 text-body-sm text-body">
        {message.content}
      </div>
    </div>
  )
}

// --- Tool activity chip ---

function ToolActivityChip({ chip }: { chip: ToolChip }) {
  const done = chip.state === "done"
  const failed = done && chip.ok === false
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-caption",
        failed
          ? "border-transparent bg-glow-red text-accent-red"
          : done
            ? "border-transparent bg-glow-green text-accent-green"
            : "border-hairline-strong bg-surface-elevated text-charcoal"
      )}
    >
      {done ? (
        failed ? (
          <X className="size-3" />
        ) : (
          <Check className="size-3" />
        )
      ) : (
        <Loader2 className="size-3 animate-spin" />
      )}
      {chip.label}
    </span>
  )
}

// --- Confirmation card ---

function ConfirmationCard({
  action,
  onResolve,
}: {
  action: AgentPendingAction
  onResolve: (confirm: boolean) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const destructive = action.tool === "delete_site"

  async function resolve(confirm: boolean) {
    setBusy(true)
    try {
      await onResolve(confirm)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        destructive
          ? "border-accent-red/40 bg-glow-red/40"
          : "border-hairline-strong bg-surface-elevated"
      )}
    >
      <div className="flex items-start gap-2">
        {destructive ? (
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-accent-red" />
        ) : (
          <Wrench className="mt-0.5 size-4 shrink-0 text-accent-blue" />
        )}
        <div className="min-w-0 flex-1">
          <p className={cn("text-body-sm", destructive ? "text-accent-red" : "text-ink")}>
            {destructive ? "Confirm destructive action" : "Confirm action"}
          </p>
          <p className="mt-1 text-body-sm break-words whitespace-pre-wrap text-charcoal">
            {action.summary || toolLabel(action.tool)}
          </p>
        </div>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void resolve(false)}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant={destructive ? "destructive" : "default"}
          disabled={busy}
          onClick={() => void resolve(true)}
        >
          {busy ? <Loader2 className="animate-spin" /> : destructive ? <Trash2 /> : <Check />}
          {destructive ? "Delete" : "Confirm"}
        </Button>
      </div>
    </div>
  )
}
