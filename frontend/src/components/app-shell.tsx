import { LogOut } from "lucide-react"
import { NavLink, Outlet } from "react-router"

import { StatusDot } from "@/components/status-dot"
import { WardressMark } from "@/components/wardress-mark"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

/*
 * App shell — nav-bar spec from DESIGN-resend.md: canvas background,
 * 64px height, single hairline bottom border, wordmark left, nav centre,
 * actions right. Content constrained to ~1200px.
 */
export function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-canvas">
      <header className="h-16 border-b border-hairline">
        <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-4 sm:px-6 lg:px-8">
          <NavLink to="/" className="flex items-center gap-3 text-ink">
            <WardressMark size={22} />
            <span className="text-heading-sm tracking-tight">Wardress</span>
          </NavLink>

          <nav className="flex items-center gap-6">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                cn(
                  "text-button-sm transition-colors",
                  isActive ? "text-ink" : "text-charcoal hover:text-ink"
                )
              }
            >
              Sites
            </NavLink>
            <NavLink
              to="/alerts"
              className={({ isActive }) =>
                cn(
                  "text-button-sm transition-colors",
                  isActive ? "text-ink" : "text-charcoal hover:text-ink"
                )
              }
            >
              Alerts
            </NavLink>
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  "text-button-sm transition-colors",
                  isActive ? "text-ink" : "text-charcoal hover:text-ink"
                )
              }
            >
              Settings
            </NavLink>
          </nav>

          <div className="flex items-center gap-4">
            <span className="flex items-center gap-2 text-caption text-charcoal">
              <StatusDot state="clean" />
              {user?.email}
            </span>
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              <LogOut />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
        <Outlet />
      </main>
    </div>
  )
}
