import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import * as apiClient from "@/lib/api"
import { ApiError, type Site } from "@/lib/api"

function baselineDot(site: Site): DotState {
  switch (site.baseline_status) {
    case "ready":
      return "clean"
    case "pending":
    case "capturing":
      return "pending"
    case "failed":
      return "threat"
    default:
      return "idle"
  }
}

function baselineLabel(site: Site): string {
  switch (site.baseline_status) {
    case "ready":
      return "Baseline ready"
    case "pending":
      return "Baseline queued"
    case "capturing":
      return "Capturing"
    case "failed":
      return "Baseline failed"
    default:
      return "No baseline"
  }
}

export function SitesPage() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState("")
  const [url, setUrl] = useState("")
  const [allowPrivate, setAllowPrivate] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const sites = useQuery({
    queryKey: ["sites"],
    queryFn: apiClient.listSites,
    // Keep capture progress fresh while any baseline is in flight
    refetchInterval: (query) =>
      query.state.data?.some(
        (s) => s.baseline_status === "pending" || s.baseline_status === "capturing"
      )
        ? 3000
        : false,
  })

  const createMutation = useMutation({
    mutationFn: apiClient.createSite,
    onSuccess: (site) => {
      void queryClient.invalidateQueries({ queryKey: ["sites"] })
      setDialogOpen(false)
      setName("")
      setUrl("")
      setAllowPrivate(false)
      setFormError(null)
      toast.success(`${site.name} added — capturing baseline`)
    },
    onError: (err) => {
      setFormError(err instanceof ApiError ? err.message : "Request failed")
    },
  })

  const deleteMutation = useMutation({
    mutationFn: apiClient.deleteSite,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sites"] })
      toast.success("Site removed")
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Delete failed")
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    createMutation.mutate({
      name,
      url,
      allow_private_networks: allowPrivate,
    })
  }

  return (
    <div>
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-display-lg text-ink">Sites</h1>
          <p className="mt-2 text-body-md text-charcoal">
            Every site under watch, with its trusted baseline.
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus />
              Add site
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add a site</DialogTitle>
              <DialogDescription>
                Wardress will capture a trusted baseline immediately after the
                site is added.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={onSubmit} className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <Label htmlFor="site-name">Name</Label>
                <Input
                  id="site-name"
                  required
                  maxLength={200}
                  placeholder="Company homepage"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="site-url">URL</Label>
                <Input
                  id="site-url"
                  type="url"
                  required
                  placeholder="https://example.com"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
              <label className="flex items-center gap-3 text-body-sm text-charcoal">
                <input
                  type="checkbox"
                  checked={allowPrivate}
                  onChange={(e) => setAllowPrivate(e.target.checked)}
                  className="size-4 accent-white"
                />
                Allow private-network target (internal hosts are blocked by
                default)
              </label>

              {formError && (
                <p role="alert" className="text-body-sm text-accent-red">
                  {formError}
                </p>
              )}

              <DialogFooter>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? "Adding" : "Add site"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="rounded-lg border border-hairline-strong bg-surface-card">
        {sites.isLoading ? (
          <p className="p-8 text-body-sm text-mute">Loading sites…</p>
        ) : sites.isError ? (
          <p className="p-8 text-body-sm text-accent-red">
            Could not load sites — is the API reachable?
          </p>
        ) : sites.data && sites.data.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Site</TableHead>
                <TableHead>URL</TableHead>
                <TableHead>Baseline</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sites.data.map((site) => (
                <TableRow key={site.id}>
                  <TableCell>
                    <Link
                      to={`/sites/${site.id}`}
                      className="text-ink hover:underline"
                    >
                      {site.name}
                    </Link>
                  </TableCell>
                  <TableCell className="max-w-md truncate text-code-md text-charcoal">
                    {site.url}
                  </TableCell>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <StatusDot state={baselineDot(site)} />
                      <span className="text-body-sm text-body">
                        {baselineLabel(site)}
                      </span>
                    </span>
                  </TableCell>
                  <TableCell className="text-body-sm text-mute">
                    {new Date(site.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Delete ${site.name}`}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Remove ${site.name} and all its scan history?`
                          )
                        ) {
                          deleteMutation.mutate(site.id)
                        }
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="flex flex-col items-center gap-3 p-16 text-center">
            <p className="text-heading-sm text-ink">No sites yet</p>
            <p className="max-w-sm text-body-sm text-charcoal">
              Add the first site to put it under watch. Wardress captures a
              trusted baseline and re-checks it on demand.
            </p>
            <Badge variant="secondary" className="mt-2">
              Phase 1 — manual scans only
            </Badge>
          </div>
        )}
      </div>
    </div>
  )
}
