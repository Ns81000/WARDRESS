import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Users } from "lucide-react"
import { toast } from "sonner"

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
        <select
          data-slot="select"
          value={user.role}
          disabled={isSelf || update.isPending}
          onChange={(e) => update.mutate({ role: e.target.value as Role })}
          className="h-8 rounded-md border border-hairline-strong bg-surface-elevated px-2 text-body-sm text-ink outline-none focus:border-white/25 disabled:opacity-50"
          aria-label={`Role for ${user.email}`}
        >
          <option value="admin">Admin</option>
          <option value="analyst">Analyst</option>
          <option value="viewer">Viewer</option>
        </select>
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
              <Users className="size-4 text-charcoal" />
              Users and roles
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
