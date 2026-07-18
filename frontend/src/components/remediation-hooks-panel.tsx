import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
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

function getActionTypeIcon(type: string, className?: string) {
  const classStr = cn("size-4 shrink-0", className)
  switch (type) {
    case "git_rollback":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 256">
          <path d="M251.17 116.6 139.4 4.82a16.49 16.49 0 0 0-23.31 0l-23.21 23.2 29.44 29.45a19.57 19.57 0 0 1 24.8 24.96l28.37 28.38a19.61 19.61 0 1 1-11.75 11.06L137.28 95.4v69.64a19.62 19.62 0 1 1-16.13-.57V94.2a19.61 19.61 0 0 1-10.65-25.73L81.46 39.44 4.83 116.08a16.49 16.49 0 0 0 0 23.32L116.6 251.17a16.49 16.49 0 0 0 23.32 0l111.25-111.25a16.5 16.5 0 0 0 0-23.33" fill="#DE4C36" />
        </svg>
      )
    case "docker_restart":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#008fe2">
          <path d="M13.98 11.08h2.12a.19.19 0 0 0 .19-.19V9.01a.19.19 0 0 0-.19-.19h-2.12a.18.18 0 0 0-.18.18v1.9c0 .1.08.18.18.18m-2.95-5.43h2.12a.19.19 0 0 0 .18-.19V3.57a.19.19 0 0 0-.18-.18h-2.12a.18.18 0 0 0-.19.18v1.9c0 .1.09.18.19.18m0 2.71h2.12a.19.19 0 0 0 .18-.18V6.29a.19.19 0 0 0-.18-.18h-2.12a.18.18 0 0 0-.19.18v1.89c0 .1.09.18.19.18m-2.93 0h2.12a.19.19 0 0 0 .18-.18V6.29a.18.18 0 0 0-.18-.18H8.1a.18.18 0 0 0-.18.18v1.89c0 .1.08.18.18.18m-2.96 0h2.11a.19.19 0 0 0 .19-.18V6.29a.18.18 0 0 0-.19-.18H5.14a.19.19 0 0 0-.19.18v1.89c0 .1.08.18.19.18m5.89 2.72h2.12a.19.19 0 0 0 .18-.19V9.01a.19.19 0 0 0-.18-.19h-2.12a.18.18 0 0 0-.19.18v1.9c0 .1.09.18.19.18m-2.93 0h2.12a.18.18 0 0 0 .18-.19V9.01a.18.18 0 0 0-.18-.19H8.1a.18.18 0 0 0-.18.18v1.9c0 .1.08.18.18.18m-2.96 0h2.11a.18.18 0 0 0 .19-.19V9.01a.18.18 0 0 0-.18-.19H5.14a.19.19 0 0 0-.19.19v1.88c0 .1.08.19.19.19m-2.92 0h2.12a.18.18 0 0 0 .18-.19V9.01a.18.18 0 0 0-.18-.19H2.22a.18.18 0 0 0-.19.18v1.9c0 .1.08.18.19.18m21.54-1.19c-.06-.05-.67-.51-1.95-.51-.34 0-.68.03-1.01.09a3.77 3.77 0 0 0-1.72-2.57l-.34-.2-.23.33a4.6 4.6 0 0 0-.6 1.43c-.24.97-.1 1.88.4 2.66a4.7 4.7 0 0 1-1.75.42H.76a.75.75 0 0 0-.76.75 11.38 11.38 0 0 0 .7 4.06 6.03 6.03 0 0 0 2.4 3.12c1.18.73 3.1 1.14 5.28 1.14.98 0 1.96-.08 2.93-.26a12.25 12.25 0 0 0 3.82-1.4 10.5 10.5 0 0 0 2.61-2.13c1.25-1.42 2-3 2.55-4.4h.23c1.37 0 2.21-.55 2.68-1 .3-.3.55-.66.7-1.06l.1-.28Z" />
        </svg>
      )
    case "custom_webhook":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 239" id="webhooks">
          <path fill="#C73A63" d="M119.54 100.503c-10.61 17.836-20.775 35.108-31.152 52.25-2.665 4.401-3.984 7.986-1.855 13.58 5.878 15.454-2.414 30.493-17.998 34.575-14.697 3.851-29.016-5.808-31.932-21.543-2.584-13.927 8.224-27.58 23.58-29.757 1.286-.184 2.6-.205 4.762-.367l23.358-39.168C73.612 95.465 64.868 78.39 66.803 57.23c1.368-14.957 7.25-27.883 18-38.477 20.59-20.288 52.002-23.573 76.246-8.001 23.284 14.958 33.948 44.094 24.858 69.031-6.854-1.858-13.756-3.732-21.343-5.79 2.854-13.865.743-26.315-8.608-36.981-6.178-7.042-14.106-10.733-23.12-12.093-18.072-2.73-35.815 8.88-41.08 26.618-5.976 20.13 3.069 36.575 27.784 48.967z" />
          <path fill="#4B4B4B" d="M149.841 79.41c7.475 13.187 15.065 26.573 22.587 39.836 38.02-11.763 66.686 9.284 76.97 31.817 12.422 27.219 3.93 59.457-20.465 76.25-25.04 17.238-56.707 14.293-78.892-7.851 5.654-4.733 11.336-9.487 17.407-14.566 21.912 14.192 41.077 13.524 55.305-3.282 12.133-14.337 11.87-35.714-.615-49.75-14.408-16.197-33.707-16.691-57.035-1.143-9.677-17.168-19.522-34.199-28.893-51.491-3.16-5.828-6.648-9.21-13.77-10.443-11.893-2.062-19.571-12.275-20.032-23.717-.453-11.316 6.214-21.545 16.634-25.53 10.322-3.949 22.435-.762 29.378 8.014 5.674 7.17 7.477 15.24 4.491 24.083-.83 2.466-1.905 4.852-3.07 7.774z" />
          <path fill="#4A4A4A" d="M167.707 187.21h-45.77c-4.387 18.044-13.863 32.612-30.19 41.876-12.693 7.2-26.373 9.641-40.933 7.29-26.808-4.323-48.728-28.456-50.658-55.63-2.184-30.784 18.975-58.147 47.178-64.293 1.947 7.071 3.915 14.21 5.862 21.264-25.876 13.202-34.832 29.836-27.59 50.636 6.375 18.304 24.484 28.337 44.147 24.457 20.08-3.962 30.204-20.65 28.968-47.432 19.036 0 38.088-.197 57.126.097 7.434.117 13.173-.654 18.773-7.208 9.22-10.784 26.191-9.811 36.121.374 10.148 10.409 9.662 27.157-1.077 37.127-10.361 9.62-26.73 9.106-36.424-1.26-1.992-2.136-3.562-4.673-5.533-7.298z" />
        </svg>
      )
    default:
      return (
        <svg className={classStr} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      )
  }
}

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
              {getActionTypeIcon("custom_webhook", "size-5")}
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
                        <span className="flex items-center gap-2">
                          {getActionTypeIcon(actionType, "size-4.5")}
                          <span>{ACTION_TYPES.find((a) => a.value === actionType)?.label}</span>
                        </span>
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
                                  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-body-sm transition-colors cursor-pointer outline-none",
                                  a.value === actionType
                                    ? "bg-primary text-primary-foreground font-medium"
                                    : "text-body hover:bg-surface-card hover:text-ink"
                                )}
                              >
                                {getActionTypeIcon(a.value, "size-4")}
                                <span>{a.label}</span>
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
                  {getActionTypeIcon(h.action_type, "size-4.5")}
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
