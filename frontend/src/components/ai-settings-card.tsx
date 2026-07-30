// Unified AI providers card (§8) — catalog-driven, any-provider. Replaces the
// old Gemini-pool + single-Ollama UI. A provider list (each backed by a
// models.dev catalog entry, or Ollama, or a custom OpenAI-compatible base),
// an add-provider flow with live validation, per-task model assignment with a
// tool-calling gate on agent chat, and the Ollama local-model download flow.
import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2, Wrench } from "lucide-react"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
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
import { CustomSelect } from "@/components/ui/select"
import * as apiClient from "@/lib/api"
import { ApiError } from "@/lib/api"

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

// Provider id -> models.dev logo. The catalog uses models.dev provider ids, so
// the logo url is derived directly (google, anthropic, groq, ...). The two
// sentinel types are mapped: `ollama` has a models.dev logo; a generic custom
// endpoint has none and always falls back to its initial.
function logoUrl(providerType: string): string | null {
  if (providerType === "openai_compatible") return null
  return `https://models.dev/logos/${providerType}.svg`
}

// A provider's logo as a plain <img> (never inlined SVG markup — that would be
// an XSS vector). Falls back to the provider's initial on a missing/broken
// logo (unknown id, offline, models.dev unreachable) via onError.
export function ProviderLogo({ providerType }: { providerType: string }) {
  const src = logoUrl(providerType)
  const [failed, setFailed] = useState(false)
  const initial = (providerType.trim()[0] || "?").toUpperCase()

  if (!src || failed) {
    return (
      <span
        aria-hidden="true"
        className="flex size-5 shrink-0 items-center justify-center rounded bg-surface-elevated text-caption font-medium text-mute"
      >
        {initial}
      </span>
    )
  }
  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      width={20}
      height={20}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="size-5 shrink-0 rounded object-contain"
      onError={() => setFailed(true)}
    />
  )
}

function validationDot(status: apiClient.AiValidationStatus): DotState {
  switch (status) {
    case "ok":
      return "clean"
    case "failed":
      return "threat"
    default:
      return "idle"
  }
}

function fmtContext(n: number | null): string | null {
  if (!n) return null
  if (n >= 1000) return `${Math.round(n / 1000)}k ctx`
  return `${n} ctx`
}

function fmtCost(model: apiClient.CatalogModel): string | null {
  if (model.cost_input == null && model.cost_output == null) return null
  const i = model.cost_input ?? 0
  const o = model.cost_output ?? 0
  if (i === 0 && o === 0) return "free"
  return `$${i}/$${o} per 1M`
}

const TASK_LABELS: Record<apiClient.AiTask, string> = {
  explanation: "Explanations",
  agent_chat: "Agent Chat",
}

// --- Add-provider dialog (searchable catalog + Ollama + custom) ------------

function AddProviderDialog({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [providerType, setProviderType] = useState("")
  const [label, setLabel] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")

  const catalog = useQuery({
    queryKey: ["ai", "catalog", "providers"],
    queryFn: apiClient.listCatalogProviders,
    enabled: open,
  })

  const isOllama = providerType === "ollama"
  const isCustom = providerType === "openai_compatible"

  const options = useMemo<apiClient.SelectOption[] | never[]>(() => {
    const base = [
      { value: "ollama", label: "Ollama (local / cloud)" },
      { value: "openai_compatible", label: "Custom (OpenAI-compatible)" },
    ]
    const cat = (catalog.data ?? []).map((p) => ({ value: p.id, label: p.name }))
    return [...base, ...cat]
  }, [catalog.data])

  const create = useMutation({
    mutationFn: () =>
      apiClient.createAiProvider({
        label: label.trim() || providerType,
        provider_type: providerType,
        api_keys: apiKey.trim() ? [apiKey.trim()] : [],
        base_url: baseUrl.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Provider added")
      setOpen(false)
      setProviderType("")
      setLabel("")
      setApiKey("")
      setBaseUrl("")
      onAdded()
    },
    onError: (err) => toast.error(errMessage(err, "Could not add the provider")),
  })

  const canSubmit =
    providerType.length > 0 &&
    (isOllama || apiKey.trim().length >= 8) &&
    (!isCustom || baseUrl.trim().length > 0)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Plus className="size-4" /> Add provider
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add an AI provider</DialogTitle>
          <DialogDescription>
            Pick any provider from the model catalog, a local/cloud Ollama, or a
            custom OpenAI-compatible endpoint. Keys are encrypted at rest.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <CustomSelect
              value={providerType}
              onChange={setProviderType}
              options={options}
              placeholder={catalog.isLoading ? "Loading catalog…" : "Select a provider"}
            />
            {providerType && (
              <div className="flex items-center gap-2 pt-0.5 text-caption text-mute">
                <ProviderLogo providerType={providerType} />
                <span className="truncate">
                  {options.find((o) => o.value === providerType)?.label ?? providerType}
                </span>
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ai-label">Label</Label>
            <Input
              id="ai-label"
              placeholder="optional display name"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          {!isOllama && (
            <div className="space-y-1.5">
              <Label htmlFor="ai-key">API key</Label>
              <Input
                id="ai-key"
                type="password"
                autoComplete="off"
                placeholder="provider API key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>
          )}
          {(isCustom || isOllama) && (
            <div className="space-y-1.5">
              <Label htmlFor="ai-base">
                Base URL{isOllama ? " (optional — cloud key enables ollama.com)" : ""}
              </Label>
              <Input
                id="ai-base"
                placeholder={isOllama ? "http://ollama:11434" : "https://…/v1"}
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>
          )}
          {isOllama && (
            <p className="text-caption text-mute">
              Leave the key empty for a local daemon. Add an Ollama Cloud key to
              reach <span className="text-code-md">:cloud</span> models.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button
            disabled={!canSubmit || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Adding…" : "Add provider"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- One provider row: models, validation, task assignment, delete --------

interface ProviderRowProps {
  provider: apiClient.AiProvider
  assignments: apiClient.AiTaskAssignment[]
  onChanged: () => void
}

function ProviderRow({ provider, assignments, onChanged }: ProviderRowProps) {
  const isOllama = provider.provider_type === "ollama"
  const [selectedModel, setSelectedModel] = useState("")

  // Catalog models for a normal provider; live Ollama models for Ollama.
  const catalogModels = useQuery({
    queryKey: ["ai", "catalog", "models", provider.provider_type],
    queryFn: () => apiClient.listCatalogModels({ providerId: provider.provider_type }),
    enabled: !isOllama,
  })
  const ollamaModels = useQuery({
    queryKey: ["ai", "ollama-models", provider.id],
    queryFn: () => apiClient.listOllamaModels(provider.id),
    enabled: isOllama,
    retry: false,
  })

  const modelOptions = useMemo<apiClient.SelectOption[]>(() => {
    if (isOllama) {
      return (ollamaModels.data ?? []).map((m) => ({
        value: m.name,
        label: m.is_cloud ? `${m.name} · cloud` : m.name,
      }))
    }
    return (catalogModels.data ?? []).map((m) => {
      const bits = [fmtContext(m.context_window), fmtCost(m)].filter(Boolean)
      const tools = m.tool_calling ? " · tools" : ""
      return {
        value: m.model_id,
        label: `${m.display_name}${bits.length ? ` (${bits.join(", ")})` : ""}${tools}`,
      }
    })
  }, [isOllama, ollamaModels.data, catalogModels.data])

  // Tool-capability of the currently-selected model (catalog only; Ollama is
  // resolved server-side at assignment time, so we allow the attempt and let
  // the backend gate return a clear 422 if it can't do tools).
  const selectedToolCapable = useMemo(() => {
    if (isOllama) return true
    const m = (catalogModels.data ?? []).find((x) => x.model_id === selectedModel)
    return m?.tool_calling ?? false
  }, [isOllama, catalogModels.data, selectedModel])

  const validate = useMutation({
    mutationFn: (modelId: string) => apiClient.validateAiProvider(provider.id, modelId),
    onSuccess: (r) => {
      if (r.ok) toast.success(r.detail)
      else toast.error(r.detail)
      onChanged()
    },
    onError: (err) => toast.error(errMessage(err, "Validation failed")),
  })

  const remove = useMutation({
    mutationFn: () => apiClient.deleteAiProvider(provider.id),
    onSuccess: () => {
      toast.success("Provider removed")
      onChanged()
    },
    onError: (err) => toast.error(errMessage(err, "Could not remove the provider")),
  })

  const assign = useMutation({
    mutationFn: (vars: { task: apiClient.AiTask; enabled: boolean; modelId: string }) =>
      apiClient.putAiAssignment(
        vars.task,
        vars.enabled
          ? { provider_id: provider.id, model_id: vars.modelId }
          : { provider_id: null, model_id: null },
      ),
    onSuccess: (_d, vars) => {
      toast.success(
        vars.enabled
          ? `${provider.label} → ${TASK_LABELS[vars.task]}`
          : `${TASK_LABELS[vars.task]} unassigned`,
      )
      onChanged()
    },
    onError: (err) => toast.error(errMessage(err, "Could not update the assignment")),
  })

  const assignedFor = (task: apiClient.AiTask) =>
    assignments.find((a) => a.task === task && a.provider_id === provider.id)

  const hints = provider.key_hints.length
    ? provider.key_hints.join(", ")
    : isOllama
      ? "no key (local)"
      : "no key"

  return (
    <li className="space-y-3 px-3 py-3">
      <div className="flex items-center gap-3">
        <StatusDot state={validationDot(provider.validation_status)} />
        <ProviderLogo providerType={provider.provider_type} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-body-sm text-body">
            <span className="truncate font-medium">{provider.label}</span>
            <span className="text-caption text-mute">{provider.provider_type}</span>
          </div>
          <p className="text-caption text-mute">
            {hints}
            {provider.validation_detail && <> · {provider.validation_detail}</>}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Remove ${provider.label}`}
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          <Trash2 className="text-mute" />
        </Button>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <CustomSelect
            value={selectedModel}
            onChange={setSelectedModel}
            options={modelOptions}
            placeholder={
              (isOllama ? ollamaModels.isLoading : catalogModels.isLoading)
                ? "Loading models…"
                : ollamaModels.isError
                  ? "Ollama unreachable"
                  : "Select a model"
            }
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={!selectedModel || validate.isPending}
          onClick={() => validate.mutate(selectedModel)}
        >
          {validate.isPending ? "Validating…" : "Validate"}
        </Button>
      </div>

      {/* Task assignment: a model can back explanations and/or agent chat.
          Agent chat is gated on tool-calling capability. */}
      <div className="flex flex-wrap gap-4 text-body-sm">
        {(["explanation", "agent_chat"] as apiClient.AiTask[]).map((task) => {
          const current = assignedFor(task)
          const checked = Boolean(current && current.model_id === selectedModel)
          const gateBlocks = task === "agent_chat" && !selectedToolCapable
          return (
            <label
              key={task}
              className="flex items-center gap-2"
              title={gateBlocks ? "This model does not support tool calling" : undefined}
            >
              <input
                type="checkbox"
                className="size-4 accent-accent-blue"
                checked={checked}
                disabled={!selectedModel || gateBlocks || assign.isPending}
                onChange={(e) =>
                  assign.mutate({ task, enabled: e.target.checked, modelId: selectedModel })
                }
              />
              <span className={gateBlocks ? "text-mute" : "text-body"}>
                Use for {TASK_LABELS[task]}
                {gateBlocks && (
                  <span className="ml-1 inline-flex items-center gap-1 text-caption text-mute">
                    <Wrench className="size-3" /> no tools
                  </span>
                )}
              </span>
            </label>
          )
        })}
      </div>

      {isOllama && ollamaModels.isError && <OllamaEnableHint />}
      {isOllama && <OllamaPull provider={provider} onPulled={() => ollamaModels.refetch()} />}
    </li>
  )
}

// --- Ollama local-model download (streamed progress) ----------------------

const OLLAMA_ENABLE_CMD = "docker compose --profile ollama up -d"

// Shown when a local Ollama provider's daemon can't be reached — the container
// ships as an opt-in Compose profile, so the operator starts it themselves. We
// can't run host Docker from inside the app container (by design), so we hand
// them the exact command to paste into PowerShell or a terminal.
export function OllamaEnableHint() {
  const copy = () => {
    void navigator.clipboard?.writeText(OLLAMA_ENABLE_CMD)
    toast.success("Command copied")
  }
  return (
    <div className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2.5">
      <p className="text-caption text-mute">
        The local Ollama container isn’t running yet. Start it once — run this in
        PowerShell or your terminal from the Wardress folder:
      </p>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded bg-surface-card px-2 py-1 text-code-md text-body">
          {OLLAMA_ENABLE_CMD}
        </code>
        <Button variant="outline" size="sm" onClick={copy}>
          Copy
        </Button>
      </div>
      <p className="text-caption text-mute">
        Then download a model below. Cloud models need no download — add an Ollama
        Cloud key to the provider instead.
      </p>
    </div>
  )
}

function OllamaPull({
  provider,
  onPulled,
}: {
  provider: apiClient.AiProvider
  onPulled: () => void
}) {
  const [model, setModel] = useState("")
  const [pulling, setPulling] = useState(false)
  const [progress, setProgress] = useState(0)
  const [statusText, setStatusText] = useState("")

  const start = async () => {
    const name = model.trim()
    if (!name || pulling) return
    setPulling(true)
    setProgress(0)
    setStatusText("Starting…")
    try {
      await apiClient.streamOllamaPull(provider.id, name, (ev) => {
        if (ev.error) {
          setStatusText(ev.error)
          return
        }
        if (ev.status) setStatusText(ev.status)
        if (ev.total && ev.completed != null) {
          setProgress(Math.min(100, Math.round((ev.completed / ev.total) * 100)))
        }
        if (ev.done && ev.status === "success") {
          setProgress(100)
        }
      })
      toast.success(`Pulled ${name}`)
      setModel("")
      onPulled()
    } catch (err) {
      toast.error(errMessage(err, "Download failed"))
    } finally {
      setPulling(false)
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-hairline bg-surface-elevated px-3 py-2.5">
      <p className="text-caption text-mute">
        Download a model to this local Ollama (recommended: llama3.2, qwen2.5).
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          className="min-w-0 flex-1"
          placeholder="llama3.2"
          value={model}
          disabled={pulling}
          onChange={(e) => setModel(e.target.value)}
        />
        <Button variant="outline" size="sm" disabled={!model.trim() || pulling} onClick={start}>
          {pulling ? "Downloading…" : "Download"}
        </Button>
      </div>
      {pulling && (
        <div className="space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-hairline">
            <div
              className="h-full rounded-full bg-accent-blue transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-caption text-mute">
            {statusText} {progress > 0 && `· ${progress}%`}
          </p>
        </div>
      )}
    </div>
  )
}

// --- Top-level card --------------------------------------------------------

export function AiSettingsCard() {
  const queryClient = useQueryClient()
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: apiClient.listAiProviders })
  const assignments = useQuery({
    queryKey: ["ai", "assignments"],
    queryFn: apiClient.getAiAssignments,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["ai", "providers"] })
    void queryClient.invalidateQueries({ queryKey: ["ai", "assignments"] })
  }

  const rows = providers.data ?? []
  const asg = assignments.data ?? []
  const explain = asg.find((a) => a.task === "explanation")
  const agent = asg.find((a) => a.task === "agent_chat")

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>AI providers</CardTitle>
            <CardDescription>
              Configure any provider from the model catalog, a local/cloud Ollama,
              or a custom OpenAI-compatible endpoint. Point Explanations and Agent
              Chat at any model. Detection works fully without AI — an unavailable
              provider is skipped silently, never blocking a scan.
            </CardDescription>
          </div>
          <AddProviderDialog onAdded={invalidate} />
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap gap-4 text-caption text-mute">
          <span>
            Explanations:{" "}
            <span className="text-body">{explain?.model_id ?? "not configured"}</span>
          </span>
          <span>
            Agent Chat:{" "}
            <span className="text-body">{agent?.model_id ?? "not configured"}</span>
          </span>
        </div>

        {rows.length === 0 ? (
          <p className="text-body-sm text-mute">
            No providers configured yet. Add one to enable AI explanations and the
            assistant.
          </p>
        ) : (
          <ul className="divide-y divide-hairline rounded-md border border-hairline">
            {rows.map((p) => (
              <ProviderRow
                key={p.id}
                provider={p}
                assignments={asg}
                onChanged={invalidate}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
