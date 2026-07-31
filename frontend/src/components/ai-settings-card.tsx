import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Cloud, ExternalLink, Plus, Search, Server, Trash2 } from "lucide-react"
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
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import * as apiClient from "@/lib/api"
import { ApiError } from "@/lib/api"

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

const KNOWN_PROVIDER_DOMAINS: Record<string, string> = {
  ollama: "ollama.com",
  openai: "openai.com",
  openai_compatible: "openai.com",
  anthropic: "anthropic.com",
  google: "ai.google.dev",
  groq: "groq.com",
  mistral: "mistral.ai",
  deepseek: "deepseek.com",
  cerebras: "cerebras.ai",
  cohere: "cohere.com",
  perplexity: "perplexity.ai",
  xai: "x.ai",
  replicate: "replicate.com",
  together: "together.ai",
  nvidia: "nvidia.com",
  "fireworks-ai": "fireworks.ai",
  openrouter: "openrouter.ai",
  lmstudio: "lmstudio.ai",
  wandb: "wandb.ai",
  zhipuai: "bigmodel.cn",
  poe: "poe.com",
  baseten: "baseten.co",
  nebius: "nebius.com",
  "nano-gpt": "nano-gpt.com",
  fastrouter: "fastrouter.ai",
  nearai: "near.ai",
  friendli: "friendli.ai",
  xiaomi: "mi.com",
  "xiaomi-token-plan": "mi.com",
  "xiaomi-token-plan-china": "mi.com",
  "xiaomi-token-plan-europe": "mi.com",
  "xiaomi-token-plan-singapore": "mi.com",
  tencent: "tencent.com",
  "tencent-tokenhub": "tencent.com",
  alibaba: "alibaba.com",
  "alibaba-cn": "alibaba.com",
  "alibaba-coding-plan": "alibaba.com",
  "alibaba-coding-plan-cn": "alibaba.com",
  "alibaba-token-plan": "alibaba.com",
  "alibaba-token-plan-cn": "alibaba.com",
  stepfun: "stepfun.com",
  minimax: "minimaxi.com",
  moonshot: "moonshot.cn",
  baichuan: "baichuan-ai.com",
  siliconflow: "siliconflow.cn",
  doubao: "volcengine.com",
  volcengine: "volcengine.com",
  bytedance: "bytedance.com",
  huawei: "huaweicloud.com",
  baidu: "baidu.com",
}

// Provider id -> multi-source logo candidate chain.
// For Custom (OpenAI-compatible), falls back to official OpenAI logo.
function buildLogoCandidates(providerType: string, domain?: string | null): string[] {
  const effectiveType = providerType === "openai_compatible" ? "openai" : providerType
  const effectiveDomain = providerType === "openai_compatible" ? "openai.com" : domain

  const slug = effectiveType.toLowerCase().replace(/_/g, "-").replace(/ /g, "-")

  const rawDomain = effectiveDomain || KNOWN_PROVIDER_DOMAINS[effectiveType] || KNOWN_PROVIDER_DOMAINS[slug] || null
  const cleanDomain = rawDomain ? rawDomain.replace(/^https?:\/\//, "").split("/")[0].split(":")[0] : null
  const rootDomain = cleanDomain && cleanDomain.includes(".") ? cleanDomain.split(".").slice(-2).join(".") : cleanDomain

  const candidates: string[] = []

  // 1. Google 128px High-Res Site Favicon (100% original full-color site logo)
  if (rootDomain && !rootDomain.startsWith("127.") && rootDomain !== "localhost") {
    candidates.push(`https://www.google.com/s2/favicons?domain=${rootDomain}&sz=128`)
  }

  // 2. full-color SVGL library
  candidates.push(`https://svgl.app/library/${slug}.svg`)

  // 3. full-color thesvg library
  candidates.push(`https://cdn.jsdelivr.net/gh/glincker/thesvg@main/public/icons/${slug}/default.svg`)

  // 4. Simple Icons brand CDN
  candidates.push(`https://cdn.simpleicons.org/${slug}`)

  // 5. Iconify Logos Gateway
  candidates.push(`https://api.iconify.design/logos/${slug}.svg`)

  // 6. models.dev (monochrome SVG fallback)
  candidates.push(`https://models.dev/logos/${effectiveType}.svg`)

  return candidates
}

// A provider's logo as a plain <img> (never inlined SVG markup — that would be
// an XSS vector). Displays in full original brand color. Falls back to a custom placeholder badge.
export function ProviderLogo({
  providerType,
  domain,
  className,
}: {
  providerType: string
  domain?: string | null
  className?: string
}) {
  const candidates = useMemo(() => buildLogoCandidates(providerType, domain), [providerType, domain])
  const [candidateIndex, setCandidateIndex] = useState(0)

  const initial = (providerType.trim()[0] || "?").toUpperCase()
  const defaultPlaceholderClasses =
    "flex size-6 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-accent-blue/20 via-surface-elevated to-surface-card border border-accent-blue/30 text-caption font-bold text-accent-blue shadow-sm"

  if (candidates.length === 0 || candidateIndex >= candidates.length) {
    return (
      <span
        aria-hidden="true"
        className={className || defaultPlaceholderClasses}
        title={providerType}
      >
        <span className="text-caption font-bold text-accent-blue">{initial !== "?" ? initial : "AI"}</span>
      </span>
    )
  }

  const currentSrc = candidates[candidateIndex]

  return (
    <img
      src={currentSrc}
      alt=""
      aria-hidden="true"
      loading="lazy"
      referrerPolicy="no-referrer"
      className={className || "size-6 shrink-0 rounded-md object-contain bg-surface-elevated/30 p-0.5 border border-hairline"}
      onLoad={(e) => {
        const img = e.currentTarget
        // Filter out Google's default 16x16 blue globe fallback icon
        if (
          currentSrc.includes("google.com/s2/favicons") &&
          img.naturalWidth > 0 &&
          img.naturalWidth <= 16 &&
          img.naturalHeight <= 16
        ) {
          setCandidateIndex((prev) => prev + 1)
        }
      }}
      onError={() => setCandidateIndex((prev) => prev + 1)}
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

// --- Add-provider dialog (Master-Detail rectangular split panel) ------------

function AddProviderDialog({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedProviderId, setSelectedProviderId] = useState("ollama")
  const [label, setLabel] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [modelId, setModelId] = useState("")
  const [ollamaMode, setOllamaMode] = useState<"local" | "cloud">("local")
  const [assignExplanation, setAssignExplanation] = useState(true)
  const [assignAgentChat, setAssignAgentChat] = useState(true)

  const catalog = useQuery({
    queryKey: ["ai", "catalog", "providers"],
    queryFn: apiClient.listCatalogProviders,
    enabled: open,
  })

  // Filter and deduplicate providers for the left sidebar list
  const providersList = useMemo(() => {
    const rawList: apiClient.CatalogProvider[] = catalog.data ?? [
      { id: "ollama", name: "Ollama", env: [], api_base: null, doc: null },
      { id: "openai_compatible", name: "Custom (OpenAI-compatible)", env: [], api_base: null, doc: null },
    ]
    const seen = new Set<string>()
    const unique: apiClient.CatalogProvider[] = []
    
    for (const p of rawList) {
      // Normalize ollama-cloud / ollama_cloud into single ollama sentinel
      const normId = (p.id === "ollama-cloud" || p.id === "ollama_cloud") ? "ollama" : p.id
      if (seen.has(normId)) continue
      seen.add(normId)
      if (normId === "ollama") {
        unique.push({ ...p, id: "ollama", name: "Ollama" })
      } else {
        unique.push(p)
      }
    }

    if (!searchQuery.trim()) return unique
    const q = searchQuery.toLowerCase().trim()
    return unique.filter((p) => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q))
  }, [catalog.data, searchQuery])

  const selectedProvider = useMemo<apiClient.CatalogProvider>(() => {
    return (
      providersList.find((p) => p.id === selectedProviderId) ||
      (catalog.data ?? []).find((p) => p.id === selectedProviderId) || {
        id: selectedProviderId,
        name: selectedProviderId === "openai_compatible" ? "Custom (OpenAI-compatible)" : selectedProviderId === "ollama" ? "Ollama" : selectedProviderId,
        env: [],
        api_base: null,
        doc: null,
      }
    )
  }, [providersList, catalog.data, selectedProviderId])

  const isOllama = selectedProviderId === "ollama"
  const isCustom = selectedProviderId === "openai_compatible"
  const providerCleanName = selectedProvider.name.replace(/ \(local \/ cloud\)/g, "")
  const catalogApiBase = selectedProvider.api_base || ""

  const isLocalOrKeyless =
    isOllama ||
    isCustom ||
    selectedProviderId.includes("lmstudio") ||
    selectedProviderId.includes("local") ||
    selectedProviderId.includes("jan") ||
    catalogApiBase.includes("127.0.0.1") ||
    catalogApiBase.includes("localhost") ||
    catalogApiBase.startsWith("http://")

  const create = useMutation({
    mutationFn: async () => {
      const created = await apiClient.createAiProvider({
        label: label.trim() || providerCleanName,
        provider_type: selectedProviderId,
        api_keys: isOllama && ollamaMode === "local" ? [] : apiKey.trim() ? [apiKey.trim()] : [],
        base_url: baseUrl.trim() || catalogApiBase || (isOllama && ollamaMode === "local" ? "http://ollama:11434" : null),
      })
      
      // Auto-assign tasks if a model ID was entered
      if (modelId.trim()) {
        const trimmedModel = modelId.trim()
        if (assignExplanation) {
          try {
            await apiClient.putAiAssignment("explanation", {
              provider_id: created.id,
              model_id: trimmedModel,
            })
          } catch {
            // silent catch on task assignment
          }
        }
        if (assignAgentChat) {
          try {
            await apiClient.putAiAssignment("agent_chat", {
              provider_id: created.id,
              model_id: trimmedModel,
            })
          } catch {
            // silent catch on task assignment
          }
        }
      }
      return created
    },
    onSuccess: () => {
      toast.success(`${providerCleanName} provider added`)
      setOpen(false)
      setSearchQuery("")
      setLabel("")
      setApiKey("")
      setBaseUrl("")
      setModelId("")
      onAdded()
    },
    onError: (err) => toast.error(errMessage(err, "Could not add the provider")),
  })

  const isOllamaCloud = isOllama && ollamaMode === "cloud"
  const isKeylessAllowed = isLocalOrKeyless && !isOllamaCloud

  const canSubmit =
    selectedProviderId.length > 0 &&
    (isKeylessAllowed || apiKey.trim().length >= 8)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Plus className="size-4" /> Add provider
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-4xl max-w-full w-[95vw] h-[640px] p-0 overflow-hidden flex flex-col md:flex-row bg-surface-card border border-hairline shadow-2xl">
        <DialogHeader className="sr-only">
          <DialogTitle>Add an AI provider</DialogTitle>
          <DialogDescription>
            Configure an AI provider with custom settings, full-color brand icons, and model assignments.
          </DialogDescription>
        </DialogHeader>

        {/* Master Panel: Left Sidebar Search & Provider List */}
        <div className="w-full md:w-72 shrink-0 border-b md:border-b-0 md:border-r border-hairline bg-surface-elevated/40 flex flex-col h-full">
          <div className="p-3 border-b border-hairline sticky top-0 bg-surface-elevated/90 backdrop-blur z-10">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 size-4 text-mute" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search 50+ providers…"
                className="pl-8 text-body-sm h-9 bg-surface-card"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {providersList.map((p) => {
              const isSelected = p.id === selectedProviderId
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setSelectedProviderId(p.id)
                    setLabel("")
                    setApiKey("")
                    setBaseUrl("")
                  }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-left text-body-sm transition-all ${
                    isSelected
                      ? "bg-accent-blue/10 border border-accent-blue/40 text-body font-medium"
                      : "hover:bg-surface-elevated text-mute hover:text-body border border-transparent"
                  }`}
                >
                  <ProviderLogo providerType={p.id} domain={p.doc || p.api_base} className="size-6 shrink-0 rounded object-contain" />
                  <span className="truncate flex-1 font-medium">{p.name}</span>
                  {isSelected && <Check className="size-4 text-accent-blue shrink-0" />}
                </button>
              )
            })}
            {providersList.length === 0 && (
              <p className="p-4 text-center text-caption text-mute">No matching providers</p>
            )}
          </div>
        </div>

        {/* Detail Panel: Right Side Form Configuration */}
        <div className="flex-1 flex flex-col h-full bg-surface-card overflow-y-auto p-6 space-y-5">
          {/* Header */}
          <div className="flex flex-col gap-2 border-b border-hairline pb-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <ProviderLogo providerType={selectedProvider.id} domain={selectedProvider.doc || selectedProvider.api_base} className="size-9 shrink-0 rounded object-contain" />
                <div>
                  <h3 className="text-body-lg font-semibold text-body">{providerCleanName}</h3>
                  <p className="text-caption text-mute">
                    Configure keys, endpoints, and model bindings for {providerCleanName}
                  </p>
                </div>
              </div>
              {selectedProvider.doc && (
                <a
                  href={selectedProvider.doc}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-caption text-accent-blue hover:underline"
                >
                  Docs <ExternalLink className="size-3" />
                </a>
              )}
            </div>

            {/* Metadata Badges */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {isOllama && (
                <span className="px-2 py-0.5 rounded text-caption font-medium bg-accent-blue/10 text-accent-blue border border-accent-blue/20">
                  {ollamaMode === "local" ? "Local Daemon" : "Ollama Cloud"}
                </span>
              )}
              {isCustom && (
                <span className="px-2 py-0.5 rounded text-caption font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20">
                  OpenAI-Compatible
                </span>
              )}
              {!isOllama && !isCustom && isLocalOrKeyless && (
                <span className="px-2 py-0.5 rounded text-caption font-medium bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
                  Local / Keyless Daemon
                </span>
              )}
              {catalogApiBase && (
                <span className="px-2 py-0.5 rounded text-caption text-mute bg-surface-elevated border border-hairline truncate max-w-xs font-mono">
                  Endpoint: {catalogApiBase}
                </span>
              )}
              {selectedProvider.env && selectedProvider.env.length > 0 && (
                <span className="px-2 py-0.5 rounded text-caption text-mute bg-surface-elevated border border-hairline font-mono">
                  Env: {selectedProvider.env[0]}
                </span>
              )}
            </div>
          </div>

          {/* Form Content */}
          <div className="space-y-4 flex-1">
            {/* Display Label */}
            <div className="space-y-1.5">
              <Label htmlFor="ai-label">Display Label</Label>
              <Input
                id="ai-label"
                placeholder={providerCleanName}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>

            {/* Special Ollama Mode Switcher & Container Startup Hint */}
            {isOllama && (
              <div className="space-y-3 rounded-lg border border-hairline bg-surface-elevated/40 p-3">
                <Label>Ollama Mode</Label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setOllamaMode("local")
                      setBaseUrl("http://ollama:11434")
                    }}
                    className={`flex items-center justify-center gap-2 py-2 px-3 rounded-md text-body-sm font-medium border transition-all ${
                      ollamaMode === "local"
                        ? "bg-accent-blue/15 border-accent-blue text-body font-semibold"
                        : "border-hairline text-mute hover:bg-surface-elevated"
                    }`}
                  >
                    <Server className="size-4" /> Local Daemon
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setOllamaMode("cloud")
                      setBaseUrl("https://ollama.com")
                    }}
                    className={`flex items-center justify-center gap-2 py-2 px-3 rounded-md text-body-sm font-medium border transition-all ${
                      ollamaMode === "cloud"
                        ? "bg-accent-blue/15 border-accent-blue text-body font-semibold"
                        : "border-hairline text-mute hover:bg-surface-elevated"
                    }`}
                  >
                    <Cloud className="size-4" /> Ollama Cloud
                  </button>
                </div>
                {ollamaMode === "local" && <OllamaEnableHint />}
              </div>
            )}

            {/* Embedded Model Downloader for Local Ollama */}
            {isOllama && ollamaMode === "local" && (
              <OllamaPull
                baseUrl={baseUrl || "http://ollama:11434"}
                onPulled={(pulledModel) => setModelId(pulledModel)}
              />
            )}

            {/* API Key / Token Input with Contextual Labeling */}
            <div className="space-y-1.5">
              <Label htmlFor="ai-key">
                {isOllamaCloud
                  ? "API Key (Required for Ollama Cloud)"
                  : isKeylessAllowed
                    ? "API Key (Optional / Keyless)"
                    : "API Key (Required)"}
              </Label>
              <Input
                id="ai-key"
                type="password"
                autoComplete="off"
                placeholder={
                  isOllamaCloud
                    ? "Paste your Ollama Cloud Bearer API key"
                    : isKeylessAllowed
                      ? `Keyless (leave empty for local ${providerCleanName}) or optional bearer token`
                      : `${providerCleanName} API key`
                }
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="text-caption text-mute">
                {isOllamaCloud
                  ? "Ollama Cloud endpoints require an Authorization Bearer API key."
                  : isKeylessAllowed
                    ? `Local inference servers (${providerCleanName}, LM Studio, LocalAI, vLLM) run keyless by default.`
                    : "Credentials are Fernet-encrypted at rest and never shared with clients."}
              </p>
            </div>

            {/* Base URL Input */}
            {(isCustom || isOllama || isLocalOrKeyless || catalogApiBase) && (
              <div className="space-y-1.5">
                <Label htmlFor="ai-base">Base URL (Optional Override)</Label>
                <Input
                  id="ai-base"
                  placeholder={catalogApiBase || (isOllama ? "http://ollama:11434" : "https://api.openai.com/v1")}
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
                <p className="text-caption text-mute">
                  {catalogApiBase
                    ? `Default: ${catalogApiBase}. Override if running a custom proxy or port.`
                    : "Custom endpoint URL (e.g. http://localhost:1234/v1 for LM Studio)."}
                </p>
              </div>
            )}

              {/* Model ID Direct Paste Input */}
              <div className="space-y-1.5">
                <Label htmlFor="ai-model">Model ID (Paste)</Label>
                <Input
                  id="ai-model"
                  placeholder={
                    isOllama
                      ? "e.g. llama3.2, qwen2.5, llama3.2:1b"
                      : "e.g. gpt-4o-mini, claude-3-5-sonnet-20241022, gemini-2.0-flash"
                  }
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                />
                <p className="text-caption text-mute">
                  Paste any model identifier supported by this provider.
                </p>
              </div>

              {/* Task Assignments */}
              {modelId.trim().length > 0 && (
                <div className="space-y-2 pt-1 border-t border-hairline">
                  <Label>Auto-Assign Tasks for {modelId}</Label>
                  <div className="flex flex-wrap gap-4 text-body-sm">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        className="size-4 accent-accent-blue"
                        checked={assignExplanation}
                        onChange={(e) => setAssignExplanation(e.target.checked)}
                      />
                      <span>Use for Explanations</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        className="size-4 accent-accent-blue"
                        checked={assignAgentChat}
                        onChange={(e) => setAssignAgentChat(e.target.checked)}
                      />
                      <span>Use for Agent Chat</span>
                    </label>
                  </div>
                </div>
              )}
            </div>

            {/* Action Footer */}
            <div className="flex items-center justify-end gap-3 pt-4 border-t border-hairline">
              <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                disabled={!canSubmit || create.isPending}
                onClick={() => create.mutate()}
              >
                {create.isPending ? "Adding Provider…" : "Add Provider"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

// --- One provider row: models, validation, task assignment, delete --------

interface ProviderRowProps {
  provider: apiClient.AiProvider
  onChanged: () => void
}

function ProviderRow({ provider, onChanged }: ProviderRowProps) {
  const isOllama = provider.provider_type === "ollama"

  const ollamaModels = useQuery({
    queryKey: ["ai", "ollama-models", provider.id],
    queryFn: () => apiClient.listOllamaModels(provider.id),
    enabled: isOllama,
    retry: false,
  })

  const remove = useMutation({
    mutationFn: () => apiClient.deleteAiProvider(provider.id),
    onSuccess: () => {
      toast.success("Provider removed")
      onChanged()
    },
    onError: (err) => toast.error(errMessage(err, "Could not remove the provider")),
  })

  const hints = provider.key_hints.length
    ? provider.key_hints.join(", ")
    : isOllama
      ? "no key (local)"
      : "no key"

  return (
    <li className="space-y-3 px-3 py-3">
      <div className="flex items-center gap-3">
        <StatusDot state={validationDot(provider.validation_status)} />
        <ProviderLogo providerType={provider.provider_type} domain={provider.base_url} className="size-6 shrink-0 rounded object-contain" />
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

      {isOllama && ollamaModels.isError && <OllamaEnableHint />}
      {isOllama && <OllamaPull providerId={provider.id} baseUrl={provider.base_url || undefined} onPulled={() => ollamaModels.refetch()} />}
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
        <Button type="button" variant="outline" size="sm" onClick={copy}>
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

function fmtBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return ""
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(1)} MB`
}

export function OllamaPull({
  providerId,
  baseUrl,
  onPulled,
}: {
  providerId?: string
  baseUrl?: string
  onPulled?: (modelName: string) => void
}) {
  const [model, setModel] = useState("")
  const [pulling, setPulling] = useState(false)
  const [progress, setProgress] = useState(0)
  const [completedBytes, setCompletedBytes] = useState(0)
  const [totalBytes, setTotalBytes] = useState(0)
  const [statusText, setStatusText] = useState("")

  const startPull = async (targetModel?: string) => {
    const name = (targetModel || model).trim()
    if (!name) {
      toast.error("Please specify a model identifier (e.g. llama3.2)")
      return
    }
    if (pulling) return
    setModel(name)
    setPulling(true)
    setProgress(0)
    setCompletedBytes(0)
    setTotalBytes(0)
    setStatusText("Initializing download connection…")

    let streamFailed = false
    try {
      await apiClient.streamOllamaPull(
        { providerId, baseUrl: baseUrl || "http://ollama:11434", model: name },
        (ev) => {
          if (ev.error) {
            streamFailed = true
            const isConnErr = ev.error.includes("Connection refused") || ev.error.includes("Could not reach")
            const friendly = isConnErr
              ? "Local Ollama server is not running yet. Start it with: docker compose --profile ollama up -d"
              : ev.error
            setStatusText(friendly)
            toast.error(friendly)
            return
          }
          if (ev.status) setStatusText(ev.status)
          if (ev.completed != null) setCompletedBytes(ev.completed)
          if (ev.total != null) setTotalBytes(ev.total)
          if (ev.total && ev.completed != null) {
            setProgress(Math.min(100, Math.round((ev.completed / ev.total) * 100)))
          }
          if (ev.done && ev.status === "success") {
            setProgress(100)
          }
        },
      )
      if (!streamFailed) {
        toast.success(`Successfully downloaded ${name}`)
        onPulled?.(name)
      }
    } catch (err) {
      toast.error(errMessage(err, "Download failed"))
    } finally {
      setPulling(false)
    }
  }

  const presets = ["llama3.2", "qwen2.5", "mistral", "deepseek-r1:8b"]

  return (
    <div className="space-y-3 rounded-lg border border-accent-blue/30 bg-accent-blue/[0.04] p-3 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-caption font-semibold text-body">Local Ollama Model Downloader</span>
        <span className="text-caption text-mute">Real-time Streamed Download</span>
      </div>

      {/* Preset Quick-Buttons */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-caption text-mute">Presets:</span>
        {presets.map((p) => (
          <button
            key={p}
            type="button"
            disabled={pulling}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              setModel(p)
            }}
            className="px-2 py-0.5 rounded text-caption font-mono bg-surface-elevated hover:bg-accent-blue/20 hover:text-accent-blue border border-hairline text-body transition-colors"
          >
            {p}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          className="min-w-0 flex-1 text-body-sm font-mono"
          placeholder="Model ID (e.g. llama3.2, qwen2.5)"
          value={model}
          disabled={pulling}
          onChange={(e) => setModel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              e.stopPropagation()
              void startPull()
            }
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!model.trim() || pulling}
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            void startPull()
          }}
        >
          {pulling ? "Downloading…" : "Download Model"}
        </Button>
      </div>

      {pulling && (
        <div className="space-y-2 rounded-md bg-surface-elevated/70 p-2.5 border border-hairline">
          <div className="flex items-center justify-between text-caption">
            <span className="truncate font-medium text-body max-w-[240px]">{statusText}</span>
            <span className="font-mono text-accent-blue font-bold">
              {progress}% {totalBytes > 0 && `(${fmtBytes(completedBytes)} / ${fmtBytes(totalBytes)})`}
            </span>
          </div>

          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-card border border-hairline">
            <div
              className="h-full rounded-full bg-gradient-to-r from-accent-blue/80 to-accent-blue transition-all duration-300 shadow-sm"
              style={{ width: `${progress}%` }}
            />
          </div>
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
            <CardTitle className="flex items-center gap-2.5">
              <img
                src="https://cdn.jsdelivr.net/gh/glincker/thesvg@main/public/icons/microsoft-fabric-iq/default.svg"
                className="size-5 shrink-0 object-contain"
                alt="AI Icon"
              />
              AI providers
            </CardTitle>
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
                onChanged={invalidate}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
