import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import * as apiClient from "@/lib/api"
import {
  refreshSession,
  setAccessToken,
  setSessionExpiredHandler,
} from "@/lib/api"

interface AuthState {
  user: apiClient.UserOut | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<apiClient.UserOut | null>(null)
  const [loading, setLoading] = useState(true)

  // On mount: try a silent refresh (HttpOnly cookie survives reloads even
  // though the in-memory access token does not). Uses the shared
  // single-flight refreshSession — StrictMode double-mounts this effect,
  // and two parallel refresh calls would trip the backend's rotated-token
  // reuse detection and revoke the session.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if ((await refreshSession()) && !cancelled) {
          const u = await apiClient.me()
          if (!cancelled) setUser(u)
        }
      } catch {
        // Not logged in - fine.
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setAccessToken(null)
      setUser(null)
    })
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await apiClient.login(email, password)
    setAccessToken(tokens.access_token)
    setUser(await apiClient.me())
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiClient.logout()
    } finally {
      setAccessToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}
