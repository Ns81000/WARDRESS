import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, Plus } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

import { StatusDot } from "@/components/status-dot"
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
import { ApiError, type Role, type UserAdmin } from "@/lib/api"
import { useAuth } from "@/lib/auth"

/*
 * User management (Phase 5 RBAC, admin-only). Invite/create users,
 * assign roles, deactivate. Role changes cut live sessions server-side.
 */

const ROLE_DESCRIPTIONS: Record<Role, string> = {
  admin: "Everything, including users, settings, and remediation hooks",
  analyst: "Sites, scans, suppression rules, alerts, and confirmations",
  viewer: "Read-only access to every page",
}

function RoleSelect({
  value,
  onChange,
  disabled
}: {
  value: string
  onChange: (val: Role) => void
  disabled?: boolean
}) {
  const [isOpen, setIsOpen] = useState(false)
  const options = [
    { value: "admin", label: "Admin" },
    { value: "analyst", label: "Analyst" },
    { value: "viewer", label: "Viewer" }
  ]
  const currentOption = options.find((opt) => opt.value === value) || options[0]

  if (disabled) {
    return (
      <div className="h-8 w-28 rounded-md border border-hairline bg-surface-deep px-2.5 text-body-sm text-mute flex items-center justify-between opacity-50 select-none">
        <span className="truncate">{currentOption.label}</span>
      </div>
    )
  }

  return (
    <div className="relative w-28">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="w-full h-8 rounded-md border border-hairline-strong bg-surface-elevated px-2.5 text-left text-body-sm text-ink outline-none focus:border-white/25 transition-colors flex items-center justify-between cursor-pointer select-none"
      >
        <span className="truncate">{currentOption.label}</span>
        <ChevronDown className={cn("size-3.5 text-charcoal transition-transform duration-200 shrink-0 ml-1.5", isOpen && "rotate-180")} />
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1 w-full rounded-md border border-hairline-strong bg-surface-card py-1 z-50 animate-detail-in font-mono text-code-md">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value as Role)
                  setIsOpen(false)
                }}
                className={cn(
                  "w-full text-left px-2.5 py-1.5 cursor-pointer transition-colors text-charcoal hover:bg-white/[0.04] hover:text-ink flex items-center justify-between",
                  opt.value === value && "text-ink bg-white/[0.02] font-medium"
                )}
              >
                <span className="truncate">{opt.label}</span>
                {opt.value === value && <span className="size-1.5 rounded-full bg-accent-blue shrink-0 ml-1.5" />}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

function UserRow({ user, isSelf }: { user: UserAdmin; isSelf: boolean }) {
  const queryClient = useQueryClient()
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["users"] })

  const update = useMutation({
    mutationFn: (body: { role?: Role; is_active?: boolean }) =>
      apiClient.updateUser(user.id, body),
    onSuccess: () => {
      invalidate()
      toast.success("User updated")
    },
    onError: (err) => toast.error(errMessage(err, "Could not update the user")),
  })

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <StatusDot state={user.is_active ? "clean" : "idle"} />
        <div className="min-w-0">
          <p className="truncate text-body-sm text-body">
            {user.email}
            {isSelf && <span className="text-mute"> (you)</span>}
            {!user.is_active && (
              <Badge variant="secondary" className="ml-2 align-middle">
                Deactivated
              </Badge>
            )}
          </p>
          <p className="text-caption text-mute">
            joined {new Date(user.created_at).toLocaleDateString()}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <RoleSelect
          value={user.role}
          disabled={isSelf || update.isPending}
          onChange={(role) => update.mutate({ role })}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={isSelf || update.isPending}
          onClick={() => {
            if (
              user.is_active &&
              !window.confirm(
                `Deactivate ${user.email}? Their sessions and API access stop working.`
              )
            ) {
              return
            }
            update.mutate({ is_active: !user.is_active })
          }}
        >
          {user.is_active ? "Deactivate" : "Reactivate"}
        </Button>
      </div>
    </li>
  )
}

export function UsersCard() {
  const { user: me } = useAuth()
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ["users"], queryFn: apiClient.listUsers })

  const [dialogOpen, setDialogOpen] = useState(false)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<Role>("analyst")
  const [formError, setFormError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => apiClient.createUser({ email, password, role }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] })
      setDialogOpen(false)
      setEmail("")
      setPassword("")
      setFormError(null)
      toast.success("User created — share the credentials securely")
    },
    onError: (err) => setFormError(errMessage(err, "Could not create the user")),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setFormError(null)
    create.mutate()
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <svg className="size-4 shrink-0 text-accent-green" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
              Users
            </CardTitle>
            <CardDescription>
              Admins manage everything; analysts run monitoring and respond to
              incidents; viewers observe. Role changes end the user&rsquo;s current
              sessions.
            </CardDescription>
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm">
                <Plus />
                Add user
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add a user</DialogTitle>
                <DialogDescription>
                  Passwords need at least 12 characters. Share them over a
                  channel you trust — they are never emailed.
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={onSubmit} className="flex flex-col gap-5">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="new-user-email">Email</Label>
                  <Input
                    id="new-user-email"
                    type="email"
                    required
                    autoComplete="off"
                    placeholder="analyst@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="new-user-password">Password</Label>
                  <Input
                    id="new-user-password"
                    type="password"
                    required
                    minLength={12}
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="new-user-role">Role</Label>
                  <select
                    id="new-user-role"
                    data-slot="select"
                    value={role}
                    onChange={(e) => setRole(e.target.value as Role)}
                    className="h-9 w-full rounded-md border border-hairline-strong bg-surface-elevated px-3 text-body-sm text-ink outline-none focus:border-white/25"
                  >
                    <option value="admin">Admin</option>
                    <option value="analyst">Analyst</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <p className="text-caption text-mute">{ROLE_DESCRIPTIONS[role]}</p>
                </div>
                {formError && (
                  <p role="alert" className="text-body-sm text-accent-red">
                    {formError}
                  </p>
                )}
                <DialogFooter>
                  <Button type="submit" disabled={create.isPending}>
                    {create.isPending ? "Creating" : "Create user"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        {users.isLoading ? (
          <p className="text-body-sm text-mute">Loading users…</p>
        ) : users.isError ? (
          <p className="text-body-sm text-accent-red">Could not load users.</p>
        ) : (
          <ul className="divide-y divide-hairline">
            {(users.data ?? []).map((u) => (
              <UserRow key={u.id} user={u} isSelf={u.id === me?.id} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
