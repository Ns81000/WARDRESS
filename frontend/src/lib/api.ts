/*
 * API client. The access token lives in module memory only (never
 * localStorage — XSS must not be able to steal a persistent credential);
 * the refresh token lives in an HttpOnly cookie scoped to /api/auth.
 * On a 401 the client attempts one silent refresh, then replays the
 * original request.
 */

let accessToken: string | null = null
let onSessionExpired: (() => void) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler
}

export class ApiError extends Error {
  status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function parseDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json()
    if (typeof body.detail === "string") return body.detail
    if (Array.isArray(body.detail) && body.detail[0]?.msg)
      return String(body.detail[0].msg)
    return `Request failed (${resp.status})`
  } catch {
    return `Request failed (${resp.status})`
  }
}

// Single-flight: every caller that needs a refresh (401 retry here, the
// boot-time silent refresh in AuthProvider) must share ONE in-flight
// call. The backend rotates the refresh token on every use and treats
// reuse of a rotated token as theft (revoking the whole family), so two
// parallel refresh requests would log the user out. Exported for
// AuthProvider; StrictMode's double-mounted effect also relies on this.
let refreshInFlight: Promise<boolean> | null = null

export function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const resp = await fetch("/api/auth/refresh", { method: "POST" })
      if (!resp.ok) return false
      const body = await resp.json()
      accessToken = body.access_token
      return true
    } catch {
      return false
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

export async function api<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const doFetch = () =>
    fetch(path, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...options.headers,
      },
    })

  let resp = await doFetch()
  if (resp.status === 401 && !path.startsWith("/api/auth/")) {
    if (await refreshSession()) {
      resp = await doFetch()
    } else {
      onSessionExpired?.()
      throw new ApiError(401, "Session expired")
    }
  }
  if (!resp.ok) throw new ApiError(resp.status, await parseDetail(resp))
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

// --- Typed API surface ---

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface UserOut {
  id: string
  email: string
  role: string
  created_at: string
}

// --- Phase 5: users, API keys, audit, remediation, health, bulk import ---

export type Role = "admin" | "analyst" | "viewer"

export interface UserAdmin {
  id: string
  email: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface ApiKeyMeta {
  id: string
  label: string
  key_prefix: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreated extends ApiKeyMeta {
  key: string
}

export interface AuditLogEntry {
  id: string
  actor_id: string | null
  actor_email: string | null
  action: string
  target_type: string
  target_id: string | null
  target_label: string | null
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  created_at: string
}

export interface AuditLogPage {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
}

export type RemediationActionType =
  | "git_rollback"
  | "docker_restart"
  | "maintenance_page_swap"
  | "custom_webhook"

export type RemediationExecutionStatus =
  | "pending_confirm"
  | "queued"
  | "succeeded"
  | "failed"
  | "dismissed"

export interface RemediationHook {
  id: string
  site_id: string
  name: string
  action_type: RemediationActionType
  trigger_threshold: number
  requires_manual_confirm: boolean
  is_active: boolean
  url_hint: string
  created_at: string
}

export interface RemediationExecution {
  id: string
  hook_id: string
  site_id: string
  scan_id: string
  status: RemediationExecutionStatus
  hook_name: string
  action_type: string
  risk_score: number | null
  detail: string | null
  confirmed_at: string | null
  executed_at: string | null
  created_at: string
  site_name: string | null
}

export interface RemediationExecutionPage {
  items: RemediationExecution[]
  total: number
  offset: number
  limit: number
}

export interface HealthComponent {
  status: string
  detail: string | null
}

export interface HealthDetails {
  status: string
  uptime_seconds: number
  queue_depth: number | null
  db_size_bytes: number | null
  sites_total: number
  scans_last_24h: number
  avg_scan_seconds: number | null
  last_scan_at: string | null
  last_dispatch_tick_at: string | null
  components: Record<string, HealthComponent>
}

export interface BulkImportRowResult {
  row: number
  url: string
  name: string | null
  status: "created" | "skipped" | "error"
  detail: string | null
  site_id: string | null
}

export interface BulkImportResult {
  total_rows: number
  created: number
  skipped: number
  errors: number
  results: BulkImportRowResult[]
}

export type BaselineStatus = "pending" | "capturing" | "ready" | "failed"
export type ScanStatus = "pending" | "running" | "completed" | "failed"
export type ScanVerdict = "clean" | "changed" | "flagged" | "error" | null

export interface Site {
  id: string
  name: string
  url: string
  allow_private_networks: boolean
  is_active: boolean
  flag_threshold: number
  auto_scan_enabled: boolean
  scan_interval_minutes: number
  current_interval_minutes: number | null
  next_scan_at: string | null
  muted_until: string | null
  created_at: string
  baseline_id: string | null
  baseline_status: BaselineStatus | null
  baseline_captured_at: string | null
  baseline_error: string | null
}

export interface Scan {
  id: string
  site_id: string
  baseline_id: string | null
  status: ScanStatus
  verdict: ScanVerdict
  content_hash: string | null
  layer_scores: Record<string, { score: number | null; skipped: boolean }> | null
  risk_score: number | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ScanFinding {
  id: string
  layer: number
  layer_key: string
  score: number | null
  skipped: boolean
  evidence: Record<string, unknown> | null
}

export interface ScanDetail extends Scan {
  findings: ScanFinding[]
  explanation: string | null
  explanation_provider: string | null
  explanation_at: string | null
}

export interface ScanPage {
  items: Scan[]
  total: number
  offset: number
  limit: number
}

export type SuppressionRuleType = "css_selector" | "regex" | "bbox"

export interface SuppressionRule {
  id: string
  site_id: string
  type: SuppressionRuleType
  value: string
  note: string | null
  created_at: string
}

export interface SiteSettingsPatch {
  flag_threshold?: number
  auto_scan_enabled?: boolean
  scan_interval_minutes?: number
  mute_minutes?: number
}

export const login = (email: string, password: string) =>
  api<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  })

export const logout = () => api<void>("/api/auth/logout", { method: "POST" })
export const me = () => api<UserOut>("/api/auth/me")

export const listSites = () => api<Site[]>("/api/sites")
export const getSite = (id: string) => api<Site>(`/api/sites/${id}`)
export const createSite = (payload: {
  name: string
  url: string
  allow_private_networks: boolean
}) =>
  api<Site>("/api/sites", { method: "POST", body: JSON.stringify(payload) })
export const deleteSite = (id: string) =>
  api<void>(`/api/sites/${id}`, { method: "DELETE" })
export const updateSite = (id: string, patch: SiteSettingsPatch) =>
  api<Site>(`/api/sites/${id}`, { method: "PATCH", body: JSON.stringify(patch) })
export const rebaseline = (id: string) =>
  api<unknown>(`/api/sites/${id}/rebaseline`, { method: "POST" })
export const scanNow = (id: string) =>
  api<Scan>(`/api/sites/${id}/scan-now`, { method: "POST" })
export const listScans = (id: string, offset = 0, limit = 50) =>
  api<ScanPage>(`/api/sites/${id}/scans?offset=${offset}&limit=${limit}`)
export const getScan = (siteId: string, scanId: string) =>
  api<ScanDetail>(`/api/sites/${siteId}/scans/${scanId}`)

export const listSuppressionRules = (siteId: string) =>
  api<SuppressionRule[]>(`/api/sites/${siteId}/suppression-rules`)
export const createSuppressionRule = (
  siteId: string,
  payload: { type: SuppressionRuleType; value: string; note?: string | null }
) =>
  api<SuppressionRule>(`/api/sites/${siteId}/suppression-rules`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
export const deleteSuppressionRule = (siteId: string, ruleId: string) =>
  api<void>(`/api/sites/${siteId}/suppression-rules/${ruleId}`, {
    method: "DELETE",
  })

// Screenshot artifact URLs (auth-required endpoints; fetched as blobs by
// useArtifact so the Authorization header rides along).
export const baselineScreenshotPath = (baselineId: string) =>
  `/api/artifacts/baselines/${baselineId}/screenshot`
export const scanScreenshotPath = (scanId: string) =>
  `/api/artifacts/scans/${scanId}/screenshot`
export const baselineHtmlPath = (baselineId: string) =>
  `/api/artifacts/baselines/${baselineId}/html`
export const scanHtmlPath = (scanId: string) =>
  `/api/artifacts/scans/${scanId}/html`

/**
 * Fetch an auth-protected artifact as an object URL (plain <img src>
 * can't carry the Authorization header). Caller owns revocation.
 */
export async function fetchArtifactObjectURL(path: string): Promise<string> {
  const resp = await artifactFetch(path)
  return URL.createObjectURL(await resp.blob())
}

/** Fetch an auth-protected text artifact (HTML snapshot) as a string. */
export async function fetchArtifactText(path: string): Promise<string> {
  return (await artifactFetch(path)).text()
}

async function artifactFetch(path: string): Promise<Response> {
  const doFetch = () =>
    fetch(path, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    })
  let resp = await doFetch()
  if (resp.status === 401) {
    if (await refreshSession()) resp = await doFetch()
    else throw new ApiError(401, "Session expired")
  }
  if (!resp.ok) throw new ApiError(resp.status, `Artifact unavailable (${resp.status})`)
  return resp
}

// --- Phase 4: settings, notification channels, alerts, reports, explain ---

export interface SmtpSettings {
  configured: boolean
  host: string | null
  port: number | null
  security: string | null
  username: string | null
  has_password: boolean
  from_addr: string | null
  from_name: string | null
}

export interface SmtpSettingsPatch {
  host: string
  port: number
  security: string
  username?: string | null
  password?: string | null
  from_addr: string
  from_name?: string | null
}

export interface TelegramSettings {
  configured: boolean
  token_hint: string | null
  chat_id: string | null
  chat_captured_at: string | null
}

export interface GeminiSettings {
  configured: boolean
  enabled: boolean
  key_hint: string | null
  model: string
}

export interface OllamaSettings {
  configured: boolean
  enabled: boolean
  base_url: string | null
  model: string | null
}

export interface TestResult {
  ok: boolean
  detail: string
}

export type ChannelType = "email" | "telegram" | "apprise_url"

export interface NotificationChannel {
  id: string
  type: ChannelType
  name: string
  site_id: string | null
  is_active: boolean
  target_hint: string
  created_at: string
}

export type DeliveryStatus = "pending" | "sent" | "failed" | "skipped"

export interface AlertDelivery {
  id: string
  channel_id: string | null
  channel_name: string
  channel_type: string
  status: DeliveryStatus
  detail: string | null
  created_at: string
  finished_at: string | null
}

export interface Alert {
  id: string
  site_id: string
  scan_id: string
  risk_score: number | null
  acknowledged_at: string | null
  acknowledged_via: string | null
  created_at: string
  site_name: string | null
  deliveries: AlertDelivery[]
}

export interface AlertPage {
  items: Alert[]
  total: number
  offset: number
  limit: number
}

export interface ExplainResult {
  explanation: string
  provider: string
  generated_at: string
  cached: boolean
}

export const getSmtpSettings = () => api<SmtpSettings>("/api/settings/smtp")
export const putSmtpSettings = (body: SmtpSettingsPatch) =>
  api<SmtpSettings>("/api/settings/smtp", { method: "PUT", body: JSON.stringify(body) })
export const testSmtp = (to: string, settings?: SmtpSettingsPatch) =>
  api<TestResult>("/api/settings/smtp/test", {
    method: "POST",
    body: JSON.stringify({ to, settings: settings ?? null }),
  })

export const getTelegramSettings = () => api<TelegramSettings>("/api/settings/telegram")
export const putTelegramSettings = (bot_token: string | null) =>
  api<TelegramSettings>("/api/settings/telegram", {
    method: "PUT",
    body: JSON.stringify({ bot_token }),
  })
export const testTelegram = () =>
  api<TestResult>("/api/settings/telegram/test", { method: "POST" })

export const getGeminiSettings = () => api<GeminiSettings>("/api/settings/gemini")
export const putGeminiSettings = (body: { api_key?: string | null; enabled: boolean }) =>
  api<GeminiSettings>("/api/settings/gemini", { method: "PUT", body: JSON.stringify(body) })
export const testGemini = () => api<TestResult>("/api/settings/gemini/test", { method: "POST" })

export const getOllamaSettings = () => api<OllamaSettings>("/api/settings/ollama")
export const putOllamaSettings = (body: {
  enabled: boolean
  base_url?: string | null
  model?: string | null
}) => api<OllamaSettings>("/api/settings/ollama", { method: "PUT", body: JSON.stringify(body) })
export const testOllama = () => api<TestResult>("/api/settings/ollama/test", { method: "POST" })

export const listChannels = () => api<NotificationChannel[]>("/api/notification-channels")
export const createChannel = (body: {
  type: ChannelType
  name: string
  site_id?: string | null
  to?: string
  url?: string
  kind?: string
}) =>
  api<NotificationChannel>("/api/notification-channels", {
    method: "POST",
    body: JSON.stringify(body),
  })
export const updateChannel = (id: string, body: { is_active?: boolean; name?: string }) =>
  api<NotificationChannel>(`/api/notification-channels/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
export const deleteChannel = (id: string) =>
  api<void>(`/api/notification-channels/${id}`, { method: "DELETE" })
export const testChannel = (id: string) =>
  api<TestResult>(`/api/notification-channels/${id}/test`, { method: "POST" })

export const listAlerts = (offset = 0, limit = 50, unacknowledgedOnly = false) =>
  api<AlertPage>(
    `/api/alerts?offset=${offset}&limit=${limit}&unacknowledged_only=${unacknowledgedOnly}`
  )
export const ackAlert = (id: string) => api<Alert>(`/api/alerts/${id}/ack`, { method: "POST" })

export const explainScan = (siteId: string, scanId: string, force = false) =>
  api<ExplainResult>(`/api/sites/${siteId}/scans/${scanId}/explain?force=${force}`, {
    method: "POST",
  })

// Report downloads carry the Authorization header via artifactFetch and
// hand back a blob URL the caller anchors to (and revokes).
export async function downloadReport(
  scanId: string,
  format: "pdf" | "markdown"
): Promise<{ url: string; filename: string }> {
  const resp = await artifactFetch(`/api/reports/${scanId}/${format}`)
  const disposition = resp.headers.get("content-disposition") ?? ""
  const match = /filename="([^"]+)"/.exec(disposition)
  const filename =
    match?.[1] ?? `wardress-report.${format === "markdown" ? "md" : "pdf"}`
  return { url: URL.createObjectURL(await resp.blob()), filename }
}

// --- Phase 5 endpoints ---

export const listUsers = () => api<UserAdmin[]>("/api/users")
export const createUser = (body: { email: string; password: string; role: Role }) =>
  api<UserAdmin>("/api/users", { method: "POST", body: JSON.stringify(body) })
export const updateUser = (
  id: string,
  body: { role?: Role; is_active?: boolean; password?: string }
) => api<UserAdmin>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(body) })
export const deleteUser = (id: string) =>
  api<void>(`/api/users/${id}`, { method: "DELETE" })

export const listApiKeys = () => api<ApiKeyMeta[]>("/api/api-keys")
export const createApiKey = (label: string) =>
  api<ApiKeyCreated>("/api/api-keys", { method: "POST", body: JSON.stringify({ label }) })
export const revokeApiKey = (id: string) =>
  api<ApiKeyMeta>(`/api/api-keys/${id}`, { method: "DELETE" })

export const listAuditLog = (params: {
  offset?: number
  limit?: number
  action?: string
  target_type?: string
  actor?: string
}) => {
  const q = new URLSearchParams()
  if (params.offset) q.set("offset", String(params.offset))
  if (params.limit) q.set("limit", String(params.limit))
  if (params.action) q.set("action", params.action)
  if (params.target_type) q.set("target_type", params.target_type)
  if (params.actor) q.set("actor", params.actor)
  return api<AuditLogPage>(`/api/audit-log?${q.toString()}`)
}

export const listRemediationHooks = (siteId: string) =>
  api<RemediationHook[]>(`/api/sites/${siteId}/remediation-hooks`)
export const createRemediationHook = (
  siteId: string,
  body: {
    name: string
    action_type: RemediationActionType
    webhook_url: string
    trigger_threshold: number
    requires_manual_confirm: boolean
  }
) =>
  api<RemediationHook>(`/api/sites/${siteId}/remediation-hooks`, {
    method: "POST",
    body: JSON.stringify(body),
  })
export const updateRemediationHook = (
  siteId: string,
  hookId: string,
  body: Partial<{
    name: string
    webhook_url: string
    trigger_threshold: number
    requires_manual_confirm: boolean
    is_active: boolean
  }>
) =>
  api<RemediationHook>(`/api/sites/${siteId}/remediation-hooks/${hookId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
export const deleteRemediationHook = (siteId: string, hookId: string) =>
  api<void>(`/api/sites/${siteId}/remediation-hooks/${hookId}`, { method: "DELETE" })

export const listRemediationExecutions = (offset = 0, limit = 50, pendingOnly = false) =>
  api<RemediationExecutionPage>(
    `/api/remediation/executions?offset=${offset}&limit=${limit}&pending_only=${pendingOnly}`
  )
export const confirmRemediation = (id: string) =>
  api<RemediationExecution>(`/api/remediation/executions/${id}/confirm`, { method: "POST" })
export const dismissRemediation = (id: string) =>
  api<RemediationExecution>(`/api/remediation/executions/${id}/dismiss`, { method: "POST" })

export const getHealthDetails = () => api<HealthDetails>("/api/health/details")

export const bulkImportSites = (body: {
  csv_text?: string
  sitemap_url?: string
  allow_private_networks?: boolean
  auto_scan_enabled?: boolean
  scan_interval_minutes?: number
}) =>
  api<BulkImportResult>("/api/sites/bulk-import", {
    method: "POST",
    body: JSON.stringify(body),
  })
