import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2, Webhook } from "lucide-react"
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
import { ApiError, type RemediationActionType, type RemediationHook } from "@/lib/api"
import { useAuth } from "@/lib/auth"

/*
 * Remediation hooks (Phase 5, §6/§9) — per-site outbound webhooks fired
 * on flagged scans. Manual confirmation is the default; auto-execute is
 * an explicit, clearly-labeled per-hook opt-in. Admin-only configuration.
 */

const ACTION_TYPES: { value: RemediationActionType; label: string; hint: string }[] = [
  {
    value: "git_rollback",
    label: "Git rollback",
    hint: "Tell your deploy tooling to roll back to the last known-good commit.",
  },
  {
    value: "docker_restart",
    label: "Docker restart",
    hint: "Restart the site's container from its clean image.",
  },
  {
    value: "maintenance_page_swap",
    label: "Maintenance page",
    hint: "Swap in a static maintenance page while you investigate.",
  },
  {
    value: "custom_webhook",
    label: "Custom webhook",
    hint: "POST the incident payload to any endpoint you run.",
  },
]

export function RemediationHooksPanel({ siteId }: { siteId: string }) {
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"
  const queryClient = useQueryClient()
  // The hook list endpoint requires the admin role (it returns redacted
  // infrastructure-config hints), so only fetch it for admins. Non-admins see
  // the panel description and a note that an admin manages these.
  const hooks = useQuery({
    queryKey: ["remediation-hooks", siteId],
    queryFn: () => apiClient.listRemediationHooks(siteId),
    enabled: isAdmin,
  })

  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState("")
  const [actionType, setActionType] = useState<RemediationActionType>("custom_webhook")
  const [webhookUrl, setWebhookUrl] = useState("")
  const [threshold, setThreshold] = useState("0.5")
  const [autoExecute, setAutoExecute] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [hookToDelete, setHookToDelete] = useState<RemediationHook | null>(null)
  const [selectOpen, setSelectOpen] = useState(false)

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["remediation-hooks", siteId] })

  const create = useMutation({
    mutationFn: () =>
      apiClient.createRemediationHook(siteId, {
        name,
        action_type: actionType,
        webhook_url: webhookUrl,
        trigger_threshold: Number(threshold) || 0.5,
        requires_manual_confirm: !autoExecute,
      }),
    onSuccess: () => {
      invalidate()
      setDialogOpen(false)
      setName("")
      setWebhookUrl("")
      setThreshold("0.5")
      setAutoExecute(false)
      setFormError(null)
      toast.success("Remediation hook added")
    },
    onError: (err) =>
      setFormError(err instanceof ApiError ? err.message : "Could not add the hook"),
  })

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      apiClient.updateRemediationHook(siteId, id, { is_active: active }),
    onSuccess: invalidate,
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not update the hook"),
  })

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.deleteRemediationHook(siteId, id),
    onSuccess: () => {
      invalidate()
      toast.success("Hook removed")
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not remove the hook"),
  })

  const actionLabel = (t: string) => ACTION_TYPES.find((a) => a.value === t)?.label ?? t

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
              <Webhook className="size-4 text-charcoal" />
              Remediation hooks
            </CardTitle>
            <CardDescription>
              When a flagged scan meets a hook&rsquo;s risk threshold, Wardress can
              notify your infrastructure to act. By default each firing waits
              in the Remediation queue for confirmation — a broken hook can
              never affect scanning.
            </CardDescription>
          </div>
          {isAdmin && (
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm">
                  <Plus />
                  Add hook
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Add a remediation hook</DialogTitle>
                  <DialogDescription>
                    Wardress POSTs a JSON incident payload to your webhook; the
                    action type tells the receiver what to do. The URL is
                    encrypted at rest.
                  </DialogDescription>
                </DialogHeader>
                <form onSubmit={onSubmit} className="flex flex-col gap-5">
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="hook-name">Name</Label>
                    <Input
                      id="hook-name"
                      required
                      placeholder="Roll back production"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="hook-action">Action type</Label>
                    <div className="relative">
                      <button
                        id="hook-action"
                        type="button"
                        onClick={() => setSelectOpen((o) => !o)}
                        className="flex h-9 w-full items-center justify-between rounded-md border border-hairline-strong bg-surface-elevated px-3 text-body-sm text-ink outline-none transition-colors hover:bg-surface-card focus:border-white/25 cursor-pointer"
                      >
                        <span>{ACTION_TYPES.find((a) => a.value === actionType)?.label}</span>
                        <span className="text-mute text-xs">▼</span>
                      </button>

                      {selectOpen && (
                        <>
                          <div className="fixed inset-0 z-40" onClick={() => setSelectOpen(false)} />
                          <div className="absolute left-0 right-0 z-50 mt-1 max-h-60 overflow-y-auto rounded-md border border-hairline-strong bg-surface-elevated p-1 shadow-2xl animate-in fade-in-0 zoom-in-95 duration-100">
                            {ACTION_TYPES.map((a) => (
                              <button
                                key={a.value}
                                type="button"
                                onClick={() => {
                                  setActionType(a.value)
                                  setSelectOpen(false)
                                }}
                                className={cn(
                                  "flex w-full items-center rounded-sm px-2 py-1.5 text-left text-body-sm transition-colors cursor-pointer outline-none",
                                  a.value === actionType
                                    ? "bg-primary text-primary-foreground font-medium"
                                    : "text-body hover:bg-surface-card hover:text-ink"
                                )}
                              >
                                {a.label}
                              </button>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                    <p className="text-caption text-mute">
                      {ACTION_TYPES.find((a) => a.value === actionType)?.hint}
                    </p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="hook-url">Webhook URL</Label>
                    <Input
                      id="hook-url"
                      required
                      autoComplete="off"
                      placeholder="https://ops.example.com/hooks/rollback"
                      value={webhookUrl}
                      onChange={(e) => setWebhookUrl(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="hook-threshold">Trigger at risk (0 to 1)</Label>
                    <Input
                      id="hook-threshold"
                      inputMode="decimal"
                      className="w-28"
                      value={threshold}
                      onChange={(e) => setThreshold(e.target.value)}
                    />
                    <p className="text-caption text-mute">
                      Fires only for flagged scans whose fused risk is at or
                      above this value.
                    </p>
                  </div>
                  <label className="flex cursor-pointer items-start gap-3 rounded-md border border-hairline p-3">
                    <span className="flex min-h-11 min-w-11 items-center justify-center md:min-h-0 md:min-w-0">
                      <input
                        type="checkbox"
                        checked={autoExecute}
                        onChange={(e) => setAutoExecute(e.target.checked)}
                        className="size-4 accent-ink"
                      />
                    </span>
                    <span className="text-body-sm text-body">
                      Auto-execute without confirmation
                      <span className="mt-0.5 block text-caption text-accent-red">
                        Fires the webhook the moment a scan is flagged — no
                        human review. Leave off unless the action is safe to
                        trigger on a false positive.
                      </span>
                    </span>
                  </label>
                  {formError && (
                    <p role="alert" className="text-body-sm text-accent-red">
                      {formError}
                    </p>
                  )}
                  <DialogFooter className="w-full sm:justify-stretch">
                    <Button type="submit" className="w-full" disabled={create.isPending}>
                      {create.isPending ? "Adding..." : "Add hook"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {!isAdmin ? (
          <p className="text-body-sm text-charcoal">
            Remediation hooks are managed by an admin.
          </p>
        ) : hooks.isLoading ? (
          <p className="text-body-sm text-mute">Loading hooks…</p>
        ) : (hooks.data ?? []).length === 0 ? (
          <p className="text-body-sm text-charcoal">No hooks configured.</p>
        ) : (
          <ul className="divide-y divide-hairline">
            {(hooks.data ?? []).map((h: RemediationHook) => (
              <li key={h.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <StatusDot state={h.is_active ? "clean" : "idle"} />
                  <div className="min-w-0">
                    <p className="truncate text-body-sm text-body">
                      {h.name}{" "}
                      <span className="text-mute">
                        · {actionLabel(h.action_type)} · {h.url_hint}
                      </span>
                    </p>
                    <p className="text-caption text-mute">
                      triggers at {Math.round(h.trigger_threshold * 100)}% risk
                      {" · "}
                      {h.requires_manual_confirm ? (
                        "manual confirmation"
                      ) : (
                        <span className="text-accent-red">auto-execute</span>
                      )}
                    </p>
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={toggle.isPending}
                      onClick={() => toggle.mutate({ id: h.id, active: !h.is_active })}
                    >
                      {h.is_active ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Delete ${h.name}`}
                      onClick={() => setHookToDelete(h)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {(hooks.data ?? []).some((h) => h.requires_manual_confirm) && (
          <p className="mt-3 text-caption text-mute">
            Pending firings appear on the{" "}
            <Badge variant="secondary" className="align-middle">
              Remediation
            </Badge>{" "}
            page for confirmation.
          </p>
        )}
      </CardContent>

      <Dialog open={hookToDelete !== null} onOpenChange={(open) => !open && setHookToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-accent-red">Remove Hook?</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove the remediation hook <span className="text-ink font-semibold">"{hookToDelete?.name}"</span>?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setHookToDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => {
                if (hookToDelete) {
                  remove.mutate(hookToDelete.id, {
                    onSuccess: () => setHookToDelete(null)
                  })
                }
              }}
            >
              {remove.isPending ? "Removing..." : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
