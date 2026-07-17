import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Copy, KeyRound, Plus } from "lucide-react"
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
import { ApiError } from "@/lib/api"

/*
 * API keys (Phase 5, §6). The raw key is shown exactly once, right after
 * creation; afterwards only the prefix identifies it. Keys carry the
 * owner's role and are revocable at any time.
 */

export function ApiKeysCard() {
  const queryClient = useQueryClient()
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: apiClient.listApiKeys })

  const [dialogOpen, setDialogOpen] = useState(false)
  const [label, setLabel] = useState("")
  const [newKey, setNewKey] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => apiClient.createApiKey(label),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] })
      setNewKey(data.key)
      setLabel("")
      setFormError(null)
    },
    onError: (err) =>
      setFormError(err instanceof ApiError ? err.message : "Could not create the key"),
  })

  const revoke = useMutation({
    mutationFn: apiClient.revokeApiKey,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] })
      toast.success("API key revoked")
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not revoke the key"),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setFormError(null)
    create.mutate()
  }

  const closeDialog = (open: boolean) => {
    setDialogOpen(open)
    if (!open) {
      setNewKey(null)
      setFormError(null)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4 text-charcoal" />
              API keys
            </CardTitle>
            <CardDescription>
              For scripting against the REST API (see /docs for the OpenAPI
              schema). Send as{" "}
              <span className="text-code-md text-body">Authorization: Bearer wk_...</span> —
              a key acts with your role and can be revoked here any time.
            </CardDescription>
          </div>
          <Dialog open={dialogOpen} onOpenChange={closeDialog}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm">
                <Plus />
                New key
              </Button>
            </DialogTrigger>
            <DialogContent>
              {newKey === null ? (
                <>
                  <DialogHeader>
                    <DialogTitle>Create an API key</DialogTitle>
                    <DialogDescription>
                      The key is shown once, immediately after creation — store
                      it in your secrets manager.
                    </DialogDescription>
                  </DialogHeader>
                  <form onSubmit={onSubmit} className="flex flex-col gap-5">
                    <div className="flex flex-col gap-2">
                      <Label htmlFor="key-label">Label</Label>
                      <Input
                        id="key-label"
                        required
                        autoComplete="off"
                        placeholder="ci-pipeline"
                        value={label}
                        onChange={(e) => setLabel(e.target.value)}
                      />
                    </div>
                    {formError && (
                      <p role="alert" className="text-body-sm text-accent-red">
                        {formError}
                      </p>
                    )}
                    <DialogFooter>
                      <Button type="submit" disabled={create.isPending || !label.trim()}>
                        {create.isPending ? "Creating" : "Create key"}
                      </Button>
                    </DialogFooter>
                  </form>
                </>
              ) : (
                <>
                  <DialogHeader>
                    <DialogTitle>Copy your new key now</DialogTitle>
                    <DialogDescription>
                      This is the only time it will be shown. Wardress stores a
                      hash, not the key itself.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 overflow-x-auto rounded-md border border-hairline bg-surface-elevated p-3 text-code-md text-body">
                      {newKey}
                    </code>
                    <Button
                      variant="outline"
                      size="icon-sm"
                      aria-label="Copy key"
                      onClick={() => {
                        void navigator.clipboard.writeText(newKey)
                        toast.success("Key copied to clipboard")
                      }}
                    >
                      <Copy />
                    </Button>
                  </div>
                  <DialogFooter>
                    <Button onClick={() => closeDialog(false)}>Done — I saved it</Button>
                  </DialogFooter>
                </>
              )}
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        {keys.isLoading ? (
          <p className="text-body-sm text-mute">Loading keys…</p>
        ) : keys.isError ? (
          <p className="text-body-sm text-accent-red">Could not load API keys.</p>
        ) : (keys.data ?? []).length === 0 ? (
          <p className="text-body-sm text-charcoal">No API keys yet.</p>
        ) : (
          <ul className="divide-y divide-hairline">
            {(keys.data ?? []).map((k) => (
              <li key={k.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <StatusDot state={k.revoked_at ? "idle" : "clean"} />
                  <div className="min-w-0">
                    <p className="truncate text-body-sm text-body">
                      {k.label}{" "}
                      <span className="text-code-md text-mute">{k.key_prefix}…</span>
                      {k.revoked_at && (
                        <Badge variant="secondary" className="ml-2 align-middle">
                          Revoked
                        </Badge>
                      )}
                    </p>
                    <p className="text-caption text-mute">
                      created {new Date(k.created_at).toLocaleDateString()}
                      {" · last used "}
                      {k.last_used_at
                        ? new Date(k.last_used_at).toLocaleString()
                        : "never"}
                    </p>
                  </div>
                </div>
                {!k.revoked_at && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Revoke "${k.label}"? Scripts using it stop working immediately.`
                        )
                      ) {
                        revoke.mutate(k.id)
                      }
                    }}
                  >
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
