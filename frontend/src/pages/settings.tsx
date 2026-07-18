import { useEffect, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Bell,
  BrainCircuit,
  Mail,
  MessageSquare,
  Plus,
  Send,
  Server,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"

import { ApiKeysCard } from "@/components/api-keys-card"
import { StatusDot } from "@/components/status-dot"
import { UsersCard } from "@/components/users-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import * as apiClient from "@/lib/api"
import { ApiError, type ChannelType } from "@/lib/api"
import { useAuth } from "@/lib/auth"

/*
 * Settings — notification channels + integrations (§8). Layout follows
 * DESIGN-resend.md: stacked cards on the true-black canvas, hairline
 * borders, one primary action per card at most, accents as text washes.
 */

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

// --- SMTP card (§8: a passing Send Test gates the Save action) ---

function SmtpCard() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ["settings", "smtp"], queryFn: apiClient.getSmtpSettings })

  const [host, setHost] = useState("")
  const [port, setPort] = useState("587")
  const [security, setSecurity] = useState("starttls")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [fromAddr, setFromAddr] = useState("")
  const [fromName, setFromName] = useState("")
  const [testTo, setTestTo] = useState("")
  const [hydrated, setHydrated] = useState(false)
  // §8: Send Test gates Save. A passing test against the *current form
  // values* unlocks Save; editing any field re-locks it.
  const [testedOk, setTestedOk] = useState(false)

  useEffect(() => {
    if (settings.data && !hydrated) {
      setHost(settings.data.host ?? "")
      setPort(String(settings.data.port ?? 587))
      setSecurity(settings.data.security ?? "starttls")
      setUsername(settings.data.username ?? "")
      setFromAddr(settings.data.from_addr ?? "")
      setFromName(settings.data.from_name ?? "")
      setHydrated(true)
    }
  }, [settings.data, hydrated])

  const formValues = (): apiClient.SmtpSettingsPatch => ({
    host,
    port: Number(port) || 587,
    security,
    username: username || null,
    // No password typed = keep/fall back to the stored one.
    password: password ? password : null,
    from_addr: fromAddr,
    from_name: fromName || null,
  })

  function edited<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v)
      setTestedOk(false)
    }
  }
  const setHostE = edited(setHost)
  const setPortE = edited(setPort)
  const setSecurityE = edited(setSecurity)
  const setUsernameE = edited(setUsername)
  const setPasswordE = edited(setPassword)
  const setFromAddrE = edited(setFromAddr)
  const setFromNameE = edited(setFromName)

  const save = useMutation({
    mutationFn: () => apiClient.putSmtpSettings(formValues()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "smtp"] })
      setPassword("")
      toast.success("SMTP settings saved")
    },
    onError: (err) => toast.error(errMessage(err, "Could not save SMTP settings")),
  })

  const test = useMutation({
    // Tests the unsaved form values so Save can require a passing test.
    mutationFn: () => apiClient.testSmtp(testTo, formValues()),
    onSuccess: (result) => {
      if (result.ok) {
        setTestedOk(true)
        toast.success(`${result.detail} — Save is unlocked`)
      } else {
        toast.error(result.detail)
      }
    },
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="size-4 text-charcoal" />
          Email (SMTP)
        </CardTitle>
        <CardDescription>
          Alert emails send through your own SMTP server. Send a test first
          — Save unlocks once a test delivery succeeds. Gmail needs an App
          Password (Google Account, Security, 2-Step Verification).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="smtp-host">Server host</Label>
              <Input
                id="smtp-host"
                required
                placeholder="smtp.example.com"
                value={host}
                onChange={(e) => setHostE(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-port">Port</Label>
              <Input
                id="smtp-port"
                inputMode="numeric"
                value={port}
                onChange={(e) => setPortE(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smtp-security">Connection security</Label>
            <select
              id="smtp-security"
              data-slot="select"
              value={security}
              onChange={(e) => setSecurityE(e.target.value)}
              className="h-9 w-full rounded-md border border-hairline-strong bg-surface-elevated px-3 text-body-sm text-ink outline-none focus:border-white/25"
            >
              <option value="starttls">STARTTLS (port 587, recommended)</option>
              <option value="tls">TLS/SSL (port 465)</option>
              <option value="none">None (unencrypted, LAN relays only)</option>
            </select>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="smtp-user">Username</Label>
              <Input
                id="smtp-user"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsernameE(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-pass">
                Password{" "}
                {settings.data?.has_password && (
                  <span className="text-mute">(stored — leave blank to keep)</span>
                )}
              </Label>
              <Input
                id="smtp-pass"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPasswordE(e.target.value)}
              />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="smtp-from">From address</Label>
              <Input
                id="smtp-from"
                required
                placeholder="wardress@example.com"
                value={fromAddr}
                onChange={(e) => setFromAddrE(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-from-name">From name</Label>
              <Input
                id="smtp-from-name"
                placeholder="Wardress"
                value={fromName}
                onChange={(e) => setFromNameE(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-4 border-t border-hairline pt-4">
            <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
              <div className="space-y-1.5">
                <Label htmlFor="smtp-test-to">Send a test to</Label>
                <Input
                  id="smtp-test-to"
                  type="email"
                  placeholder="you@example.com"
                  className="w-56"
                  value={testTo}
                  onChange={(e) => setTestTo(e.target.value)}
                />
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!host || !fromAddr || !testTo || test.isPending}
                onClick={() => test.mutate()}
              >
                <Send />
                {test.isPending ? "Sending" : "Send test"}
              </Button>
            </div>
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={!testedOk || save.isPending}
              title={testedOk ? undefined : "Send a successful test first"}
            >
              Save SMTP settings
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// --- Telegram card (§8 setup flow: token -> /start -> captured chat) ---

function TelegramCard() {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ["settings", "telegram"],
    queryFn: apiClient.getTelegramSettings,
    // While waiting for /start, poll so the captured chat appears live.
    refetchInterval: (query) =>
      query.state.data?.configured && !query.state.data.chat_id ? 4000 : false,
  })
  const [token, setToken] = useState("")

  const save = useMutation({
    mutationFn: (value: string | null) => apiClient.putTelegramSettings(value),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "telegram"] })
      setToken("")
      toast.success(
        data.configured
          ? "Bot token saved — now open your bot in Telegram and send /start"
          : "Telegram configuration cleared"
      )
    },
    onError: (err) => toast.error(errMessage(err, "Could not save the bot token")),
  })

  const test = useMutation({
    mutationFn: apiClient.testTelegram,
    onSuccess: (result) => (result.ok ? toast.success(result.detail) : toast.error(result.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const s = settings.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquare className="size-4 text-charcoal" />
          Telegram
        </CardTitle>
        <CardDescription>
          Two-way bot: alert pushes plus /status, /sites, /scan, /ack, /mute
          and /explain from your phone.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="list-decimal space-y-1 pl-5 text-body-sm text-charcoal">
          <li>
            Message <span className="text-code-md text-body">@BotFather</span> in Telegram and
            create a bot with <span className="text-code-md text-body">/newbot</span>.
          </li>
          <li>Paste the token it gives you below and save.</li>
          <li>
            Start the bot container (
            <span className="text-code-md text-body">docker compose --profile telegram up -d</span>
            ), open your bot, and send{" "}
            <span className="text-code-md text-body">/start</span> — the chat is captured
            automatically.
          </li>
        </ol>

        {s?.configured ? (
          <div className="space-y-2 rounded-md border border-hairline bg-surface-elevated p-4">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={s.chat_id ? "clean" : "pending"} />
              {s.chat_id
                ? `Connected — chat ${s.chat_id} captured ${s.chat_captured_at ?? ""}`
                : "Token saved — waiting for /start from your Telegram account"}
            </div>
            <p className="text-caption text-mute">Token {s.token_hint}</p>
          </div>
        ) : null}

        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-64">
            <Label htmlFor="tg-token">Bot token</Label>
            <Input
              id="tg-token"
              autoComplete="off"
              placeholder="1234567890:AA..."
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={!token || save.isPending}
            onClick={() => save.mutate(token)}
          >
            Save token
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!s?.configured || !s.chat_id || test.isPending}
            onClick={() => test.mutate()}
          >
            <Send />
            Send test message
          </Button>
          {s?.configured && (
            <Button
              variant="ghost"
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate("")}
            >
              Disconnect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// --- AI providers card (Gemini + Ollama, §8) ---

function AiCard() {
  const queryClient = useQueryClient()
  const gemini = useQuery({ queryKey: ["settings", "gemini"], queryFn: apiClient.getGeminiSettings })
  const ollama = useQuery({ queryKey: ["settings", "ollama"], queryFn: apiClient.getOllamaSettings })

  const [apiKey, setApiKey] = useState("")
  const [ollamaModel, setOllamaModel] = useState("")
  const [ollamaHydrated, setOllamaHydrated] = useState(false)

  useEffect(() => {
    if (ollama.data && !ollamaHydrated) {
      setOllamaModel(ollama.data.model ?? "")
      setOllamaHydrated(true)
    }
  }, [ollama.data, ollamaHydrated])

  const saveGemini = useMutation({
    mutationFn: (body: { api_key?: string | null; enabled: boolean }) =>
      apiClient.putGeminiSettings(body),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "gemini"] })
      setApiKey("")
      toast.success(data.configured ? "Gemini key saved" : "Gemini key removed")
    },
    onError: (err) => toast.error(errMessage(err, "Could not save the Gemini key")),
  })

  const testGeminiM = useMutation({
    mutationFn: apiClient.testGemini,
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const saveOllama = useMutation({
    mutationFn: (enabled: boolean) =>
      apiClient.putOllamaSettings({ enabled, model: ollamaModel || null }),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "ollama"] })
      toast.success(data.enabled ? "Ollama enabled" : "Ollama settings saved")
    },
    onError: (err) => toast.error(errMessage(err, "Could not save Ollama settings")),
  })

  const testOllamaM = useMutation({
    mutationFn: apiClient.testOllama,
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BrainCircuit className="size-4 text-charcoal" />
          AI analysis
        </CardTitle>
        <CardDescription>
          Optional. Ambiguous scans get a semantic second opinion, and incident
          pages gain an &ldquo;Explain this incident&rdquo; summary. Detection works fully
          without it — an unavailable provider is skipped silently, never
          blocking a scan.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={gemini.data?.configured ? "clean" : "idle"} />
              Google Gemini ({gemini.data?.model ?? "gemini-2.5-flash"})
              {gemini.data?.configured && (
                <span className="text-caption text-mute">key {gemini.data.key_hint}</span>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!gemini.data?.configured || testGeminiM.isPending}
                onClick={() => testGeminiM.mutate()}
              >
                {testGeminiM.isPending ? "Testing" : "Test key"}
              </Button>
              {gemini.data?.configured && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => saveGemini.mutate({ api_key: "", enabled: false })}
                >
                  Remove
                </Button>
              )}
            </div>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-64">
              <Label htmlFor="gemini-key">API key</Label>
              <Input
                id="gemini-key"
                type="password"
                autoComplete="off"
                placeholder="AIza..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={!apiKey || saveGemini.isPending}
              onClick={() => saveGemini.mutate({ api_key: apiKey, enabled: true })}
            >
              Save key
            </Button>
          </div>
          <p className="text-caption text-mute">
            Free-tier keys work; requests are rate-limited well inside the free
            quota and only ambiguous scans consult the model.
          </p>
        </div>

        <div className="space-y-3 border-t border-hairline pt-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={ollama.data?.enabled ? "clean" : "idle"} />
              Ollama (local, no cloud)
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!ollama.data?.enabled || testOllamaM.isPending}
                onClick={() => testOllamaM.mutate()}
              >
                {testOllamaM.isPending ? "Testing" : "Test"}
              </Button>
            </div>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-64">
              <Label htmlFor="ollama-model">Model</Label>
              <Input
                id="ollama-model"
                placeholder="llama3.2"
                value={ollamaModel}
                onChange={(e) => setOllamaModel(e.target.value)}
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={saveOllama.isPending || (!ollama.data?.enabled && !ollamaModel)}
              onClick={() => saveOllama.mutate(!ollama.data?.enabled)}
            >
              {ollama.data?.enabled ? "Disable" : "Enable"}
            </Button>
          </div>
          <p className="text-caption text-mute">
            Needs the ollama compose profile running (
            <span className="text-code-md">docker compose --profile ollama up -d</span>) with the
            model pulled. Gemini is preferred when both are enabled.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

// --- Notification channels card ---

const CHANNEL_PRESETS: {
  key: string
  label: string
  kind: string
  placeholder: string
  hint: string
  recommended?: boolean
}[] = [
  {
    key: "ntfy",
    label: "ntfy",
    kind: "ntfy",
    placeholder: "ntfy://your-private-topic",
    hint: "Easiest push option: pick a unique topic, subscribe in the ntfy app.",
    recommended: true,
  },
  {
    key: "discord",
    label: "Discord",
    kind: "discord",
    placeholder: "discord://webhook_id/webhook_token",
    hint: "From a channel webhook URL: discord.com/api/webhooks/{id}/{token}.",
  },
  {
    key: "slack",
    label: "Slack",
    kind: "slack",
    placeholder: "slack://TokenA/TokenB/TokenC",
    hint: "From an incoming-webhook URL's three token segments.",
  },
  {
    key: "webhook",
    label: "Webhook",
    kind: "webhook",
    placeholder: "json://host/path or https URL via json://",
    hint: "POSTs a JSON payload to any endpoint you run.",
  },
  {
    key: "other",
    label: "Other",
    kind: "apprise",
    placeholder: "scheme://... (any Apprise URL)",
    hint: "Any of the 100+ Apprise services — matrix://, gotify://, pover://, ...",
  },
]

function ChannelsCard() {
  const queryClient = useQueryClient()
  const channels = useQuery({ queryKey: ["channels"], queryFn: apiClient.listChannels })
  const sites = useQuery({ queryKey: ["sites"], queryFn: apiClient.listSites })

  const [dialogOpen, setDialogOpen] = useState(false)
  const [chanType, setChanType] = useState<ChannelType>("apprise_url")
  const [preset, setPreset] = useState(CHANNEL_PRESETS[0])
  const [name, setName] = useState("")
  const [to, setTo] = useState("")
  const [url, setUrl] = useState("")
  const [siteId, setSiteId] = useState<string>("")
  const [formError, setFormError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      apiClient.createChannel({
        type: chanType,
        name,
        site_id: siteId || null,
        ...(chanType === "email" ? { to } : {}),
        ...(chanType === "apprise_url" ? { url, kind: preset.kind } : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] })
      setDialogOpen(false)
      setName("")
      setTo("")
      setUrl("")
      setSiteId("")
      setFormError(null)
      toast.success("Channel added — send it a test")
    },
    onError: (err) => setFormError(errMessage(err, "Could not add the channel")),
  })

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      apiClient.updateChannel(id, { is_active: active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["channels"] }),
    onError: (err) => toast.error(errMessage(err, "Could not update the channel")),
  })

  const remove = useMutation({
    mutationFn: apiClient.deleteChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] })
      toast.success("Channel removed")
    },
    onError: (err) => toast.error(errMessage(err, "Could not remove the channel")),
  })

  const test = useMutation({
    mutationFn: apiClient.testChannel,
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const siteName = (id: string | null) =>
    id ? (sites.data?.find((s) => s.id === id)?.name ?? "one site") : "All sites"

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Bell className="size-4 text-charcoal" />
              Alert channels
            </CardTitle>
            <CardDescription>
              Where flagged scans go. Channels apply to every site unless
              scoped to one; failures are recorded per delivery and shown on
              the Alerts page.
            </CardDescription>
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm">
                <Plus />
                Add channel
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add an alert channel</DialogTitle>
                <DialogDescription>
                  Alerts fire when a scan's fused risk crosses the site's flag
                  threshold.
                </DialogDescription>
              </DialogHeader>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  setFormError(null)
                  create.mutate()
                }}
                className="flex flex-col gap-5"
              >
                <div className="flex flex-wrap gap-2">
                  {CHANNEL_PRESETS.map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      onClick={() => {
                        setPreset(p)
                        setChanType("apprise_url")
                      }}
                      className={`rounded-md border px-3 py-1.5 text-button-sm transition-colors ${
                        chanType === "apprise_url" && preset.key === p.key
                          ? "border-white/40 text-ink"
                          : "border-hairline-strong text-charcoal hover:text-ink"
                      }`}
                    >
                      {p.label}
                      {p.recommended ? " (recommended)" : ""}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => setChanType("email")}
                    className={`rounded-md border px-3 py-1.5 text-button-sm transition-colors ${
                      chanType === "email"
                        ? "border-white/40 text-ink"
                        : "border-hairline-strong text-charcoal hover:text-ink"
                    }`}
                  >
                    Email
                  </button>
                  <button
                    type="button"
                    onClick={() => setChanType("telegram")}
                    className={`rounded-md border px-3 py-1.5 text-button-sm transition-colors ${
                      chanType === "telegram"
                        ? "border-white/40 text-ink"
                        : "border-hairline-strong text-charcoal hover:text-ink"
                    }`}
                  >
                    Telegram
                  </button>
                </div>

                <div className="flex flex-col gap-2">
                  <Label htmlFor="chan-name">Name</Label>
                  <Input
                    id="chan-name"
                    required
                    placeholder="Ops alerts"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>

                {chanType === "email" && (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="chan-to">Recipient address</Label>
                    <Input
                      id="chan-to"
                      type="email"
                      required
                      placeholder="oncall@example.com"
                      value={to}
                      onChange={(e) => setTo(e.target.value)}
                    />
                    <p className="text-caption text-mute">
                      Sends through the SMTP settings above.
                    </p>
                  </div>
                )}

                {chanType === "apprise_url" && (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="chan-url">Service URL</Label>
                    <Input
                      id="chan-url"
                      required
                      autoComplete="off"
                      placeholder={preset.placeholder}
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                    />
                    <p className="text-caption text-mute">{preset.hint}</p>
                  </div>
                )}

                {chanType === "telegram" && (
                  <p className="text-body-sm text-charcoal">
                    Pushes to the Telegram chat captured in the Telegram card
                    above — configure that first.
                  </p>
                )}

                <div className="flex flex-col gap-2">
                  <Label htmlFor="chan-site">Scope</Label>
                  <select
                    id="chan-site"
                    data-slot="select"
                    value={siteId}
                    onChange={(e) => setSiteId(e.target.value)}
                    className="h-9 w-full rounded-md border border-hairline-strong bg-surface-elevated px-3 text-body-sm text-ink outline-none focus:border-white/25"
                  >
                    <option value="">All sites</option>
                    {(sites.data ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        Only {s.name}
                      </option>
                    ))}
                  </select>
                </div>

                {formError && (
                  <p role="alert" className="text-body-sm text-accent-red">
                    {formError}
                  </p>
                )}
                <DialogFooter>
                  <Button type="submit" disabled={create.isPending}>
                    {create.isPending ? "Adding" : "Add channel"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        {channels.isLoading ? (
          <p className="text-body-sm text-mute">Loading channels…</p>
        ) : (channels.data ?? []).length === 0 ? (
          <p className="text-body-sm text-charcoal">
            No channels yet — alerts are only visible in the dashboard until
            you add one.
          </p>
        ) : (
          <ul className="divide-y divide-hairline">
            {(channels.data ?? []).map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-4 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <StatusDot state={c.is_active ? "clean" : "idle"} />
                  <div className="min-w-0">
                    <p className="truncate text-body-sm text-body">
                      {c.name}{" "}
                      <span className="text-mute">
                        · {c.type === "apprise_url" ? "service" : c.type} · {c.target_hint}
                      </span>
                    </p>
                    <p className="text-caption text-mute">{siteName(c.site_id)}</p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={test.isPending}
                    onClick={() => test.mutate(c.id)}
                  >
                    <Send />
                    Test
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={toggle.isPending}
                    onClick={() => toggle.mutate({ id: c.id, active: !c.is_active })}
                  >
                    {c.is_active ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete ${c.name}`}
                    onClick={() => {
                      if (window.confirm(`Remove the channel "${c.name}"?`)) {
                        remove.mutate(c.id)
                      }
                    }}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-display-lg text-ink">Settings</h1>
        <p className="mt-2 text-body-md text-charcoal">
          {isAdmin
            ? "Notifications, intelligence, users, and API access. Everything here is optional — and nothing here can break a scan."
            : "Your API keys. Notification and integration settings are managed by an admin."}
        </p>
      </div>
      <div className="space-y-6">
        {/* Everyone manages their own API keys; the rest is admin scope
            (the API enforces this server-side — hiding is just UX). */}
        <ApiKeysCard />
        {isAdmin && (
          <>
            <UsersCard />
            <ChannelsCard />
            <SmtpCard />
            <TelegramCard />
            <AiCard />
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Server className="size-4 text-charcoal" />
                  Secrets at rest
                </CardTitle>
                <CardDescription>
                  SMTP passwords, service URLs, bot tokens and API keys are
                  encrypted with your instance&rsquo;s CREDENTIALS_ENCRYPTION_KEY before
                  they reach the database, and never returned by the API.{" "}
                  <Badge variant="secondary" className="align-middle">
                    Fernet / AES-128-CBC + HMAC
                  </Badge>
                </CardDescription>
              </CardHeader>
            </Card>
          </>
        )}
      </div>
    </div>
  )
}
