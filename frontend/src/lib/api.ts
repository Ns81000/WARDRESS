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
