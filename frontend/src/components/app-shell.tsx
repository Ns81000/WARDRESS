import { useState } from "react"
import { LogOut, Menu, X } from "lucide-react"
import { NavLink, Outlet } from "react-router"

import { StatusDot } from "@/components/status-dot"
import { WardressMark } from "@/components/wardress-mark"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

/*
 * App shell — nav-bar spec from DESIGN-resend.md: canvas background,
 * 64px height, single hairline bottom border, wordmark left, nav centre,
 * actions right. Content constrained to ~1200px. Phase 5 adds
 * Remediation/Health for everyone and Audit for admins (the API enforces
 * roles server-side; hiding links is UX, not security).
 */
export function AppShell() {
  const { user, logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const isAdmin = user?.role === "admin"

  const items = [
    { to: "/", label: "Sites", end: true },
    { to: "/alerts", label: "Alerts" },
    { to: "/assistant", label: "Assistant" },
    { to: "/remediation", label: "Remediation" },
    { to: "/health", label: "Health" },
    ...(isAdmin ? [{ to: "/audit", label: "Audit" }] : []),
    { to: "/settings", label: "Settings" },
  ]

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-hairline">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-4 sm:px-6 lg:px-8">
          <NavLink to="/" className="flex items-center gap-3 text-ink">
            <WardressMark size={22} />
            <span className="text-heading-sm tracking-tight">Wardress</span>
          </NavLink>

          <nav className="hidden items-center gap-5 lg:flex">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "text-button-sm transition-colors",
                    isActive ? "text-ink" : "text-charcoal hover:text-ink"
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="hidden items-center gap-4 lg:flex">
            <span className="flex items-center gap-2 text-caption text-charcoal">
              <StatusDot state="clean" />
              {user?.email}
              {user?.role && user.role !== "admin" && (
                <span className="text-mute">· {user.role}</span>
              )}
            </span>
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              <LogOut />
              Sign out
            </Button>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X /> : <Menu />}
          </Button>
        </div>
        {menuOpen && (
          <div className="border-t border-hairline bg-canvas lg:hidden">
            <div className="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-4 sm:px-6">
              <nav className="grid gap-2">
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    onClick={() => setMenuOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        "rounded-md px-3 py-2 text-button-sm transition-colors",
                        isActive
                          ? "bg-surface-elevated text-ink"
                          : "text-charcoal hover:bg-surface-elevated hover:text-ink"
                      )
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </nav>
              <div className="flex flex-col gap-3 border-t border-hairline pt-4">
                <span className="flex items-center gap-2 truncate text-caption text-charcoal">
                  <StatusDot state="clean" />
                  {user?.email}
                  {user?.role && user.role !== "admin" && (
                    <span className="text-mute">· {user.role}</span>
                  )}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => {
                    setMenuOpen(false)
                    void logout()
                  }}
                >
                  <LogOut />
                  Sign out
                </Button>
              </div>
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
        <Outlet />
      </main>
    </div>
  )
}
