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

async function tryRefresh(): Promise<boolean> {
  const resp = await fetch("/api/auth/refresh", { method: "POST" })
  if (!resp.ok) return false
  const body = await resp.json()
  accessToken = body.access_token
  return true
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
    if (await tryRefresh()) {
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
export type ScanVerdict = "clean" | "changed" | "error" | null

export interface Site {
  id: string
  name: string
  url: string
  allow_private_networks: boolean
  is_active: boolean
  created_at: string
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
  layer_scores: Record<string, { score: number; evidence: Record<string, unknown> }> | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
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
export const rebaseline = (id: string) =>
  api<unknown>(`/api/sites/${id}/rebaseline`, { method: "POST" })
export const scanNow = (id: string) =>
  api<Scan>(`/api/sites/${id}/scan-now`, { method: "POST" })
export const listScans = (id: string) => api<Scan[]>(`/api/sites/${id}/scans`)
