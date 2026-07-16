import { useState, type FormEvent } from "react"
import { Navigate } from "react-router"

import { WardressMark } from "@/components/wardress-mark"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"

/*
 * Login — a single surface-card on the black canvas with the accent-blue
 * atmospheric glow anchored at the top of the section (one glow per
 * section, low opacity, per the design doc's elevation rules).
 */
export function LoginPage() {
  const { user, loading, login } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email, password)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reach the server"
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-canvas px-6">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[600px]"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 0%, var(--color-glow-blue), transparent 70%)",
        }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-10 flex flex-col items-center gap-4 text-ink">
          <WardressMark size={48} />
          <div className="text-center">
            <h1 className="font-display text-[40px] leading-none tracking-tight">
              Wardress
            </h1>
            <p className="mt-3 text-subtitle text-charcoal">
              The watch that never stands down.
            </p>
          </div>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-lg border border-hairline-strong bg-surface-card p-8"
        >
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error && (
              <p role="alert" className="text-body-sm text-accent-red">
                {error}
              </p>
            )}

            <Button type="submit" disabled={submitting} className="mt-1 w-full">
              {submitting ? "Signing in" : "Sign in"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
